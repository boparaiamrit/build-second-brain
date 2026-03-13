---
name: build-second-brain
description: >
  Analyze one or more git repositories commit-by-commit from the very first commit using maximum parallel agents
  to extract engineering patterns, architecture decisions, debugging approaches, scaling strategies,
  and coding conventions — then build a structured "second brain" knowledge base with a personalized
  engineer profile and hybrid global/local Claude memory injection. Supports multi-repo analysis
  (frontend + backend, microservices) to capture cross-repo patterns. Use this skill when the user
  mentions "second brain", "analyze my repo", "extract my patterns", "learn from my commits",
  "build my brain", "reverse engineer my thinking", "learn how I code", "analyze git history",
  or wants to capture their engineering decision-making from a codebase. Also trigger when the user
  wants to create an engineer profile, extract architecture patterns from commits, build a knowledge
  base from code history, or analyze multiple repositories together.
---

# Build Second Brain

Extract an engineer's thinking patterns, architecture decisions, and coding philosophy from their git history — commit by commit, using maximum parallel agents — and build a structured knowledge base + engineer profile.

## Overview

This skill runs a three-phase pipeline:
1. **HARVEST** — Parallel agents analyze every commit, writing findings to scratchpad files
2. **CATEGORIZE** — 10 category agents organize findings into knowledge domains
3. **SYNTHESIZE** — Build the final second brain directory, engineer profile, and Claude memory

Every agent writes to disk immediately. Nothing is kept only in memory. If context compresses or an agent crashes, all work persists in scratchpad files and can be resumed.

## Step 0: Gather Inputs & Preflight

Ask the user for three things (or accept as arguments):

1. **Repo path(s)** — "What's the path to the git repo(s) you want to analyze? (comma-separated for multiple)"
   - Single repo: `/path/to/my-app`
   - Multiple repos: `/path/to/backend, /path/to/frontend`
2. **Brain name** — "What should we name this brain?" (default: "Second Brain")
   - Examples: "Amrit's Brain", "Komal's Brain", "DevTeam Brain"
3. **Memory scope** — "Where should the brain's memory live?"
   - `hybrid` (default, recommended): Core identity goes global, repo-specific patterns stay local
   - `global`: Everything goes to global memory (available in all projects)
   - `local`: Everything stays in the current project's memory only

Then run preflight checks **for each repo**:

```bash
# For each repo path:
REPO_PATH="$(cd <repo_path> && pwd)"
REPO_ID="$(basename "$REPO_PATH")"  # e.g., "my-backend"
git -C "$REPO_PATH" rev-list --count HEAD
git -C "$REPO_PATH" rev-parse HEAD  # Record HEAD hash

# Verify Python is available (needed for indexer)
python3 --version 2>/dev/null || python --version 2>/dev/null
```

**Preflight gates:**
- If any repo has 0 commits or `git rev-list` fails: abort with "Repo <path> has no commits to analyze."
- If Python is not available: warn user, plan to use inline indexing fallback.
- If total commits across all repos > 5000: warn user and suggest using batch size 50 instead of 20.

Report the commit counts:
> "Found **N repos** with **X total commits** (repo-a: 500, repo-b: 300). I'll split them into batches of Z and use parallel agents to analyze every single one. Memory scope: hybrid. Estimated token usage: ~3M-6M per 1000 commits. Proceed?"

Wait for confirmation.

**IMPORTANT — Resolve absolute paths now and use them everywhere:**

```bash
WORK_DIR="$(pwd)/.second-brain"
BRAIN_NAME="<user's chosen name>"
SCOPE="hybrid"  # or global or local
BATCH_SIZE=20   # or 50 if >5000 total commits

# Per repo (build arrays):
REPO_PATHS=("<abs_path_1>" "<abs_path_2>" ...)
REPO_IDS=("<repo-id-1>" "<repo-id-2>" ...)
```

Store these in `.second-brain/config.md`. ALL subsequent steps, agent prompts, and bash commands MUST use these absolute paths — never relative paths like `.second-brain/`.

## Step 1: Initialize

### Resume Check

Before initializing, check if `.second-brain/progress.md` already exists:

```bash
test -f .second-brain/progress.md && echo "RESUME" || echo "FRESH"
```

If resuming, read `progress.md` and determine the current state:
- Parse which Phase 1 batches have `[x]` checkmarks
- Parse which Phase 2 categories have `[x]` checkmarks
- Parse which Phase 3 steps have `[x]` checkmarks
- Resume from the **first unchecked item**, not just batch count

Ask: "Found existing progress — Phase N in progress, X% complete. Resume? (y/n)"

### Fresh Start

Create the working directory structure:

```bash
mkdir -p "$WORK_DIR/scratchpad" "$WORK_DIR/indexed" "$WORK_DIR/categories"
```

Write `$WORK_DIR/config.md`:
```markdown
# Second Brain Config
Brain Name: <BRAIN_NAME>
Work Dir: <WORK_DIR> (absolute)
Memory Scope: <SCOPE> (hybrid/global/local)
Batch Size: <BATCH_SIZE>
Started: <timestamp>

## Repos
| Repo ID | Path | Commits | HEAD Hash |
|---------|------|---------|-----------|
| <repo-id-1> | <abs_path_1> | <N1> | <hash1> |
| <repo-id-2> | <abs_path_2> | <N2> | <hash2> |

Total Commits: <N1+N2+...>
Total Batches: <ceil(N1/BATCH_SIZE) + ceil(N2/BATCH_SIZE) + ...>
```

## Step 2: Get All Commits

For **each repo**, extract commits into a separate file using `git -C`:

```bash
# For each repo:
git -C "$REPO_PATH" log --format="%H|%s|%ai" --reverse > "$WORK_DIR/<REPO_ID>-commits.txt"
```

Write initial `progress.md` with one checkbox line per batch **per repo**, per category, per synthesis step. Use the format from [references/progress-template.md](references/progress-template.md) but replace pseudocode with actual generated lines. Group Phase 1 batches by repo.

## Step 3: Phase 1 — HARVEST

This is the most critical phase. Every commit gets analyzed. **For multi-repo, harvest each repo independently** — spawn a team/wave per repo, or interleave batches from all repos into a single team's task list.

### Agent Teams Mode (preferred)

Try Agent Teams for self-balancing workload:

1. Create a team with 5 teammates using `TeamCreate`
2. For each repo, for each batch, add a task to the team's shared task list via `TodoWrite` — each task specifies repo ID, repo path, batch number, start line, end line in `<REPO_ID>-commits.txt`
3. Each teammate claims tasks, processes them, and marks complete

The prompt for each teammate is in [references/harvest-agent-prompt.md](references/harvest-agent-prompt.md). Read it and use it as the agent prompt, filling in these **absolute paths**:
- `REPO_PATH`: absolute path to the repo (from the task — varies per batch in multi-repo)
- `REPO_ID`: short identifier for the repo (e.g., "my-backend")
- `COMMITS_FILE`: absolute path to `$WORK_DIR/<REPO_ID>-commits.txt`
- `SCRATCHPAD_DIR`: absolute path to `$WORK_DIR/scratchpad/`
- `BATCH_SIZE`: the configured batch size
- `BATCH_ASSIGNMENT`: For Teams mode: "Claim tasks from the team's shared task list using TodoWrite. Each task specifies a repo ID, repo path, batch number, and line range. Mark each task complete after writing its scratchpad file."

**If TeamCreate fails**, fall to Fallback Mode.

### Fallback Mode (if teams unavailable)

Spawn background subagents in waves of 5:

1. Spawn 5 agents with `run_in_background: true`
2. Each agent gets statically assigned batches (across all repos): agent 1 gets batches 1,6,11,...; agent 2 gets 2,7,12,...; etc.
3. Collect the agent IDs returned from each spawn
4. Use `TaskOutput` to poll each agent ID until all 5 complete
5. Spawn next wave of 5
6. Repeat until all batches processed
7. Use the same harvest agent prompt, but fill `BATCH_ASSIGNMENT` with explicit batch numbers and repo IDs: "Process: my-backend batch 1, my-frontend batch 2, ..."

### Progress Monitoring

After launching harvest agents, set up a progress monitor using `CronCreate`:

```
Expression: "*/2 * * * *"
Prompt: "Run: ls $WORK_DIR/scratchpad/batch-*.md 2>/dev/null | wc -l
         Read $WORK_DIR/config.md for total batches.
         Calculate and report percentage."
Recurring: true
```

Store the cron job ID so it can be cancelled later (on success OR failure).

### Phase 1 Completion Verification

After all agents complete, verify **per repo**:
1. Count `batch-<REPO_ID>-*.md` files for each repo — must equal that repo's batch count
2. For each batch file, count `## Commit:` headers — flag any files with fewer commits than expected batch size (last batch may have fewer)
3. If any batch files are missing or incomplete, re-spawn agents for those batches only

## Step 4: Phase 1.5 — INDEX

Split scratchpad findings by category tag so each Phase 2 agent reads only its relevant content.

**Locate the indexer script** — it ships with this skill at:
```
skills/build-second-brain/scripts/indexer.py
```
Resolve its absolute path by checking the skill's installation directory.

```bash
python3 indexer.py "$WORK_DIR/scratchpad" "$WORK_DIR/indexed"
```

If the exact script path cannot be resolved, or Python is unavailable, do it with bash:

```bash
for category in architecture tech-stack debugging scaling security data-modeling code-style refactoring integration error-handling; do
  grep -B 100 "### Category Tags" "$WORK_DIR"/scratchpad/batch-*.md | \
    grep -A 100 "$category" > "$WORK_DIR/indexed/${category}-raw.md" 2>/dev/null || true
done
```

**Note:** The bash fallback is approximate. The Python indexer is preferred for accuracy.

The indexer also produces `$WORK_DIR/indexed/statistics-raw.md` with pre-computed counts per category, total commits parsed, and commits per month. This feeds into Phase 3.

## Step 5: Phase 2 — CATEGORIZE

Spawn category agents in **two waves of 5** (not all 10 at once — prevents resource exhaustion):

**Wave 1:** architecture, tech-stack, debugging, scaling, security
**Wave 2:** data-modeling, code-style, refactoring, integration, error-handling

Each agent's prompt is templated from [references/category-agent-prompt.md](references/category-agent-prompt.md). Fill in:
- `CATEGORY_NAME`: the category (e.g., "Architecture")
- `CATEGORY_SLUG`: the slug (e.g., "architecture")
- `CATEGORY_DESCRIPTION`: what to extract (from the table below)
- `INDEXED_FILE`: **absolute path** to `$WORK_DIR/indexed/<slug>-raw.md`
- `OUTPUT_FILE`: **absolute path** to `$WORK_DIR/categories/<slug>.md`
- `BRAIN_NAME`: from config

| Category | Slug | Description (for CATEGORY_DESCRIPTION) |
|----------|------|----------|
| Architecture | `architecture` | System structure decisions, module boundaries, service splits, folder organization, layering patterns |
| Tech Stack | `tech-stack` | Library/framework/tool choices and the reasoning behind picking one over alternatives |
| Debugging | `debugging` | Bug patterns, root causes, diagnostic steps taken, fix approaches, what broke and why |
| Scaling | `scaling` | Queues, workers, caching strategies, async patterns, load handling, performance optimizations |
| Security | `security` | Auth mechanisms, input validation, sanitization, access control, secrets management |
| Data Modeling | `data-modeling` | Schema design, migration patterns, relationships, indexes, query optimization |
| Code Style | `code-style` | Naming conventions, file structure, import patterns, code organization, formatting rules |
| Refactoring | `refactoring` | What was messy before, why it was cleaned up, before/after patterns, triggers for refactoring |
| Integration | `integration` | External API connections, webhook handling, third-party service patterns, SDK usage |
| Error Handling | `error-handling` | Retry logic, fallbacks, circuit breakers, logging strategies, monitoring, alerting |

For each wave: spawn 5 background agents, collect agent IDs, poll with `TaskOutput` until all complete. Then spawn the next wave.

After both waves, verify all 10 category files exist. If any are missing (agent crashed), re-spawn just that agent.

## Step 6: Phase 3 — SYNTHESIZE

Run 3 agents **sequentially** (each depends on the previous):

### Agent 1: Brain Builder

Read the prompt from [references/brain-builder-prompt.md](references/brain-builder-prompt.md). Fill in:
- `CATEGORIES_DIR`: absolute path to `$WORK_DIR/categories/`
- `OUTPUT_DIR`: absolute path to `second-brain/` in the working directory
- `BRAIN_NAME`: from config
- `REPO_LIST`: from config (all repo IDs and paths)
- `TOTAL_COMMITS`: from config
- `STATISTICS_FILE`: absolute path to `$WORK_DIR/indexed/statistics-raw.md`

**Important:** The Brain Builder should NOT read scratchpad files directly. For `raw/commit-log.md`, use a bash command to generate it:
```bash
grep "^## Commit:\|^Message:" "$WORK_DIR"/scratchpad/batch-*.md > "$OUTPUT_DIR/raw/commit-log.md"
```
For `raw/statistics.md`, use the pre-computed `statistics-raw.md` from the indexer.

### Agent 2: Profile Generator

Read the prompt from [references/profile-generator-prompt.md](references/profile-generator-prompt.md). Fill in:
- `CATEGORIES_DIR`: absolute path
- `OUTPUT_DIR`: absolute path
- `BRAIN_NAME`, `REPO_LIST`, `TOTAL_COMMITS`: from config

### Agent 3: Memory Injector

Read the prompt from [references/memory-injector-prompt.md](references/memory-injector-prompt.md). Fill in:
- `PROFILE_FILE`: absolute path to `second-brain/profile/engineer-profile.md`
- `PATTERNS_DIR`: absolute path to `second-brain/patterns/`
- `DECISIONS_FILE`: absolute path to `second-brain/decisions/tech-decisions.md`
- `BRAIN_NAME`: from config
- `SCOPE`: from config (`hybrid`, `global`, or `local`)

**Resolve memory directories BEFORE spawning this agent:**
```bash
# Global memory directory (always exists or create it)
GLOBAL_MEMORY_DIR="$HOME/.claude/memory"
mkdir -p "$GLOBAL_MEMORY_DIR"

# Local (project-specific) memory directory
LOCAL_MEMORY_DIR=$(ls -d ~/.claude/projects/*/memory/ 2>/dev/null | head -1)
```

Pass the resolved absolute paths to the agent based on scope:
- `hybrid`: pass both `GLOBAL_MEMORY_DIR` and `LOCAL_MEMORY_DIR`
- `global`: pass only `GLOBAL_MEMORY_DIR`
- `local`: pass only `LOCAL_MEMORY_DIR`

## Step 7: Verify & Report

After all phases complete:

1. Verify all expected output files exist in `second-brain/`
2. Verify the engineer profile is non-empty (at least 100 lines)
3. Verify Claude memory files were written
4. Update `progress.md` to show 100% completion
5. **Cancel the progress monitor cron job** (use stored cron job ID)

Report to the user:

```
BUILD COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  second-brain/                        — your full knowledge base
  second-brain/profile/engineer-profile.md — "<Brain Name>" engineer DNA
  second-brain/patterns/               — X patterns across 10 categories
  second-brain/playbooks/              — debugging & scaling playbooks

  Memory scope: <hybrid/global/local>
  Global memory: ~/.claude/memory/     — core identity (loads everywhere)
  Local memory: ~/.claude/projects/... — repo patterns (loads in project)

  Repos analyzed: <list of repo IDs>
  Commits analyzed: <N total> (<per-repo breakdown>)
  Patterns found: <count>
  Categories covered: <count>/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Error Recovery

- **Agent fails mid-batch**: Scratchpad file has partial progress. On resume, count `## Commit:` headers — if fewer than expected, re-run from the last recorded commit hash. The harvest agent checks for existing entries before re-analyzing.
- **Context compresses**: All findings are on disk in scratchpad files. Re-read `$WORK_DIR/config.md` to restore state.
- **Large diffs (>500 lines)**: Agents fall back to `git show --stat` + selective inspection. Binary files are skipped.
- **Empty categories**: Categories with <3 findings get "No significant patterns detected." Phase 3 handles gracefully — Brain Builder skips missing/empty category files.
- **>5000 commits**: Batch size increased to 50 (user confirmed in Step 0).
- **Merge commits**: Agents use `git show --stat` first. If empty, log as "Empty merge." If has changes, analyze selectively.
- **Cron job cleanup**: Cancel cron job on BOTH success and failure paths.
- **Missing category file**: Re-spawn just that category agent rather than re-running all of Phase 2.
