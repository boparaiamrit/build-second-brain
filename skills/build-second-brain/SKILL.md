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
2. **CATEGORIZE** — 12 category agents organize findings into knowledge domains
3. **SYNTHESIZE** — Build the final second brain directory, engineer profile, and Claude memory

Every agent writes to disk immediately. Nothing is kept only in memory. If context compresses or an agent crashes, all work persists in scratchpad files and can be resumed.

## Runtime Enforcement (Hooks & Loops)

This skill uses **hooks** and **CronCreate loops** to enforce spec compliance during execution — not just after the fact.

### Hooks (automatic, fire on every tool call)

| Hook | Event | What It Enforces |
|------|-------|-----------------|
| `validate-write-paths.sh` | **PreToolUse** (Write/Edit) | Blocks relative paths to `.second-brain/` or `second-brain/`. Blocks batch files missing REPO_ID prefix. |
| Inline bash | **PreToolUse** (Bash) | Warns on relative paths in bash commands targeting build directories. |
| `validate-scratchpad-output.sh` | **PostToolUse** (Write) | Validates scratchpad batch files have `## Commit:` headers and `### Category Tags` sections. |
| `validate-agent-completion.sh` | **SubagentStop** | Reports current scratchpad/category file counts after every agent completes. |
| Inline bash | **Stop** | Blocks session stop if profile is missing or progress.md has unchecked items. |
| Inline bash | **PreCompact** | Reminds to re-read config.md and progress.md after context compaction. |

These hooks are **conditionally active** — they only fire when `$CLAUDE_PROJECT_DIR/.second-brain/config.md` exists (i.e., during an active build). Outside of a build, they silently exit 0.

### CronCreate Loops (set up during execution)

| Loop | Phase | What It Monitors |
|------|-------|-----------------|
| `HARVEST_CRON_ID` | Phase 1 | Counts scratchpad files every 2 min, reports % complete |
| `CATEGORIZE_CRON_ID` | Phase 2 | Counts category files every 2 min, reports N/12 complete |

Both cron jobs must be cancelled with `CronDelete` when their phase completes (success or failure).

**IMPORTANT — Persist cron IDs to disk** so they can be recovered after a crash or context compression:

```bash
echo "Harvest Cron ID: <ID>" >> "$WORK_DIR/config.md"
echo "Categorize Cron ID: <ID>" >> "$WORK_DIR/config.md"
```

On resume, read cron IDs from `config.md` to cancel orphaned jobs with `CronDelete`.

### Verification Script (post-run)

After the build completes, run the verification script for a comprehensive check:

```bash
$PYTHON_CMD <SKILL_DIR>/scripts/verify.py "$WORK_DIR" "$OUTPUT_DIR"
```

Where `$PYTHON_CMD` is the Python command discovered during preflight (`python3` or `python`). If Python was not available, skip verification.

This checks 12 test groups: config fields, batch naming, commit coverage, profile quality, and more.

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

# Verify Python is available (needed for indexer + verify scripts)
# Try python3 first, then python. Store whichever works as PYTHON_CMD.
if python3 --version 2>/dev/null; then
  PYTHON_CMD="python3"
elif python --version 2>/dev/null; then
  PYTHON_CMD="python"
else
  PYTHON_CMD=""
fi
```

**Preflight gates:**
- If a repo has 0 commits or `git rev-list` fails: warn the user and **skip that repo** (continue with the remaining repos). If ALL repos fail, abort.
- If `PYTHON_CMD` is empty (Python not found): warn user with install guidance:
  > "Python 3.7+ is required for the indexer and verification scripts but was not found. Install it from https://python.org or via your package manager (`brew install python3` / `apt install python3` / `winget install Python.Python.3`). I can fall back to a less-accurate bash indexer, but verification will be skipped. Continue anyway?"
  - If user continues: plan to use inline bash indexing fallback and skip verify.py.
  - Store `PYTHON_CMD` in config.md so downstream phases know which command to use.
- If total commits across all repos > 5000: warn user and suggest using batch size 50 instead of 20.

### Artifact Discovery

For **each repo**, scan for planning/design/documentation artifacts that reveal thinking philosophy beyond code. These are gold mines — they show how the person thinks about products, breaks down problems, and communicates decisions.

```bash
# For each repo, discover artifact files (docs, planning, memory, configs)
ARTIFACT_DIRS=()
for dir in docs .planning .claude .github; do
  [ -d "$REPO_PATH/$dir" ] && ARTIFACT_DIRS+=("$REPO_PATH/$dir")
done

# Also find root-level markdown files (README, CONTRIBUTING, CLAUDE.md, etc.)
ROOT_MDS=$(find "$REPO_PATH" -maxdepth 1 -name "*.md" -type f 2>/dev/null)

# Find nested docs directories (e.g., src/docs/, packages/*/docs/)
NESTED_DOCS=$(find "$REPO_PATH" -maxdepth 3 -type d -name "docs" 2>/dev/null)
```

**What to scan for (ordered by value):**
- `docs/` — design specs, requirements, ADRs, architecture decision records
- `.planning/` — GSD roadmaps, phase plans, PROJECT.md, research files
- `.claude/` — memory files, CLAUDE.md (reveals non-negotiables and workflow preferences)
- `.github/` — PR templates, issue templates (reveals process expectations)
- Root `.md` files — README, CONTRIBUTING, CHANGELOG (reveals communication style)
- `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` — project instructions (reveals coding philosophy)

**Chronological ordering:** For each discovered artifact, use `git log --format="%ai" --diff-filter=A -- <file>` to find when it was first created. Sort artifacts by creation date — this reveals the order of thinking (what was important enough to document first).

Store the discovered artifact manifest in `$WORK_DIR/artifacts.md`:
```markdown
# Discovered Artifacts
Repo: <REPO_ID>

| File | Created | Last Modified | Type |
|------|---------|---------------|------|
| docs/specs/auth-design.md | 2024-01-15 | 2024-03-20 | design-spec |
| .planning/PROJECT.md | 2024-02-01 | 2024-06-15 | planning |
| CLAUDE.md | 2024-03-01 | 2024-07-01 | project-instructions |
```

Report the full discovery:
> "Found **N repos** with **X total commits** (repo-a: 500, repo-b: 300) and **Y artifact files** (design specs, planning docs, project instructions). I'll analyze commits in batches of Z with parallel agents, plus harvest all artifacts for philosophy and product thinking. Memory scope: hybrid. Estimated token usage: ~3M-6M per 1000 commits. Proceed?"

Wait for confirmation.

**IMPORTANT — Resolve absolute paths now and use them everywhere:**

```bash
WORK_DIR="$(pwd)/.second-brain"
OUTPUT_DIR="$(pwd)/second-brain"
BRAIN_NAME="<user's chosen name>"
SCOPE="hybrid"  # or global or local
BATCH_SIZE=20   # or 50 if >5000 total commits

# Per repo (build arrays):
REPO_PATHS=("<abs_path_1>" "<abs_path_2>" ...)
REPO_IDS=("<repo-id-1>" "<repo-id-2>" ...)
```

Store these in `$WORK_DIR/config.md`. ALL subsequent steps, agent prompts, and bash commands MUST use these absolute paths — never relative paths like `.second-brain/` or `second-brain/`.

## Step 1: Initialize

### Resume Check

Before initializing, check if `$WORK_DIR/progress.md` already exists:

```bash
test -f "$WORK_DIR/progress.md" && echo "RESUME" || echo "FRESH"
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
Output Dir: <OUTPUT_DIR> (absolute)
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
Python Command: <$PYTHON_CMD>
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

### Progress Monitoring (CronCreate Loop)

After launching harvest agents, set up a progress monitor using `CronCreate`:

```
Expression: "*/2 * * * *"
Prompt: "Run: ls <LITERAL_WORK_DIR>/scratchpad/batch-*.md 2>/dev/null | wc -l
         Read <LITERAL_WORK_DIR>/config.md for total batches.
         Calculate and report percentage.
         If percentage >= 100, report HARVEST COMPLETE."
Recurring: true
```

**IMPORTANT:** Replace `<LITERAL_WORK_DIR>` with the actual resolved absolute path (e.g., `/home/user/project/.second-brain`). Do NOT pass shell variables like `$WORK_DIR` — cron prompts execute in a separate context where those variables don't exist.

Store the cron job ID as `HARVEST_CRON_ID` — write it to `$WORK_DIR/config.md` immediately so it can be recovered after a crash.

### Wave Completion Loop (Fallback Mode)

When using wave-based agents, enforce a strict completion loop for each wave:

```
WAVE = 1
while batches remain:
  1. Spawn up to 5 background agents for this wave
  2. Collect all agent IDs into WAVE_AGENT_IDS
  3. POLL LOOP: For each agent ID in WAVE_AGENT_IDS:
     - Call TaskOutput with the agent ID
     - If agent still running, continue polling
     - If agent complete, mark its batches done in progress.md
  4. VERIFY LOOP: After all 5 agents complete:
     - For each expected batch file: check file exists AND has correct ## Commit: count
     - If any batch missing or incomplete → re-spawn ONLY that batch
     - Repeat verify until all batches for this wave pass
  5. Update progress.md: mark all wave batches [x]
  6. WAVE += 1
```

**The PostToolUse hook on Write validates scratchpad structure automatically** — if a batch file is written without `## Commit:` headers or `### Category Tags` sections, the hook raises a warning.

### Phase 1 Completion Verification

After all agents complete, verify **per repo**:
1. Count `batch-<REPO_ID>-*.md` files for each repo — must equal that repo's batch count
2. For each batch file, count `## Commit:` headers — flag any files with fewer commits than expected batch size (last batch may have fewer)
3. If any batch files are missing or incomplete, re-spawn agents for those batches only
4. Cancel `HARVEST_CRON_ID` with `CronDelete`

## Step 3.5: Phase 1A — HARVEST ARTIFACTS

After commit harvesting, mine the non-code artifacts for philosophy, product thinking, and planning patterns. These files reveal HOW someone thinks — not just what they coded.

**If no artifacts were discovered in preflight**, skip this step.

Spawn a background agent using the prompt from [references/artifact-harvest-prompt.md](references/artifact-harvest-prompt.md). Fill in:
- `ARTIFACTS_MANIFEST`: absolute path to `$WORK_DIR/artifacts.md`
- `SCRATCHPAD_DIR`: absolute path to `$WORK_DIR/scratchpad/`
- `REPO_LIST`: from config (all repo IDs and absolute paths — agent needs these for `git log --follow`)
- `BRAIN_NAME`: from config

The artifact agent reads each discovered file, extracts philosophy/product-thinking/planning patterns, and writes findings to scratchpad files named `artifacts-<REPO_ID>.md` using the same category tag format as commit findings (so the indexer picks them up automatically).

**Key difference from commit harvest:** Artifacts are read directly (not via `git show`). But the agent also checks `git log --follow -- <file>` to understand how each artifact evolved over time — what was added, removed, or restructured reveals changing priorities.

Poll with `TaskOutput` until complete. Verify `artifacts-<REPO_ID>.md` files exist in scratchpad for each repo that had artifacts.

## Step 4: Phase 1.5 — INDEX

Split scratchpad findings by category tag so each Phase 2 agent reads only its relevant content. The indexer processes BOTH commit findings (`batch-*.md`) AND artifact findings (`artifacts-*.md`) from the scratchpad directory.

**Locate the indexer script** — it ships with this skill at:
```
skills/build-second-brain/scripts/indexer.py
```
Resolve its absolute path by checking the skill's installation directory.

```bash
$PYTHON_CMD "$SKILL_DIR/scripts/indexer.py" "$WORK_DIR/scratchpad" "$WORK_DIR/indexed"
```

Where `$SKILL_DIR` is the resolved absolute path to the `skills/build-second-brain/` directory.

If the exact script path cannot be resolved, or Python is unavailable, do it with bash:

```bash
for category in architecture tech-stack debugging scaling security data-modeling code-style refactoring integration error-handling product-thinking workflow; do
  grep -B 100 "### Category Tags" "$WORK_DIR"/scratchpad/{batch,artifacts}-*.md | \
    grep -A 100 "$category" > "$WORK_DIR/indexed/${category}-raw.md" 2>/dev/null || true
done
```

**Note:** The bash fallback is approximate. The Python indexer is preferred for accuracy.

The indexer also produces `$WORK_DIR/indexed/statistics-raw.md` with pre-computed counts per category, total commits parsed, and commits per month. This feeds into Phase 3.

## Step 5: Phase 2 — CATEGORIZE

Spawn category agents in **two waves of 6** (not all 12 at once — prevents resource exhaustion):

**Wave 1:** architecture, tech-stack, debugging, scaling, security, product-thinking
**Wave 2:** data-modeling, code-style, refactoring, integration, error-handling, workflow

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
| Product Thinking | `product-thinking` | Feature scoping, requirements analysis, trade-off decisions, roadmap priorities, user-centric design choices, what was built vs explicitly rejected |
| Workflow | `workflow` | Planning patterns, process decisions, communication style, documentation habits, tool/system choices, review processes, how work is broken down and sequenced |

### Phase 2 Progress Monitoring (CronCreate Loop)

Set up a second progress monitor before spawning Wave 1:

```
Expression: "*/2 * * * *"
Prompt: "Run: ls <LITERAL_WORK_DIR>/categories/*.md 2>/dev/null | wc -l
         Expected: 12 category files.
         Report: N/12 categories complete.
         If N >= 12, report CATEGORIZE COMPLETE."
Recurring: true
```

Store as `CATEGORIZE_CRON_ID` — write to `$WORK_DIR/config.md` for crash recovery.

### Wave Completion Loop

For each wave, enforce strict completion:

```
WAVE 1 (architecture, tech-stack, debugging, scaling, security, product-thinking):
  1. Spawn 6 background agents, collect agent IDs
  2. POLL LOOP: TaskOutput each agent ID until all 6 complete
  3. VERIFY: Check all 6 category files exist in $WORK_DIR/categories/
  4. RE-SPAWN any missing category agents
  5. Update progress.md: mark Wave 1 categories [x]

WAVE 2 (data-modeling, code-style, refactoring, integration, error-handling, workflow):
  Same loop as Wave 1
```

**The SubagentStop hook fires after each agent completes** — it reports current scratchpad and category file counts automatically.

### Phase 2 Completion Verification

After both waves:
1. Verify all 12 category files exist — if any are missing (agent crashed), re-spawn just that agent
2. Cancel `CATEGORIZE_CRON_ID` with `CronDelete`

## Step 6: Phase 3 — SYNTHESIZE

Run 3 agents **sequentially** — each depends on the previous, so you MUST wait for each to complete before spawning the next:

```
1. Spawn Agent 1 (Brain Builder) with run_in_background: true
2. Poll with TaskOutput until Agent 1 completes
3. VERIFY: Check $OUTPUT_DIR/patterns/ and $OUTPUT_DIR/decisions/ exist
4. Spawn Agent 2 (Profile Generator) with run_in_background: true
5. Poll with TaskOutput until Agent 2 completes
6. VERIFY: Check $OUTPUT_DIR/profile/engineer-profile.md exists and has 100+ lines
7. Spawn Agent 3 (Memory Injector) with run_in_background: true
8. Poll with TaskOutput until Agent 3 completes
9. VERIFY: Check memory files were written
10. Update progress.md: mark all Phase 3 steps [x]
```

### Pre-step: Generate commit-log.md

Before spawning any Phase 3 agents, generate the commit log and create the output directory:

```bash
mkdir -p "$OUTPUT_DIR/raw"
grep "^## Commit:\|^Repo:\|^Message:" "$WORK_DIR"/scratchpad/batch-*.md > "$OUTPUT_DIR/raw/commit-log.md"
```

### Agent 1: Brain Builder

Read the prompt from [references/brain-builder-prompt.md](references/brain-builder-prompt.md). Fill in:
- `CATEGORIES_DIR`: absolute path to `$WORK_DIR/categories/`
- `OUTPUT_DIR`: absolute path (from config — the resolved `$OUTPUT_DIR`)
- `BRAIN_NAME`: from config
- `REPO_LIST`: from config (all repo IDs and paths)
- `TOTAL_COMMITS`: from config
- `STATISTICS_FILE`: absolute path to `$WORK_DIR/indexed/statistics-raw.md`

**Important:** The Brain Builder should NOT read scratchpad files directly. `raw/commit-log.md` was already generated in the pre-step above. For `raw/statistics.md`, use the pre-computed `statistics-raw.md` from the indexer.

### Agent 2: Profile Generator

Read the prompt from [references/profile-generator-prompt.md](references/profile-generator-prompt.md). Fill in:
- `CATEGORIES_DIR`: absolute path
- `OUTPUT_DIR`: absolute path
- `BRAIN_NAME`, `REPO_LIST`, `TOTAL_COMMITS`: from config

### Agent 3: Memory Injector

Read the prompt from [references/memory-injector-prompt.md](references/memory-injector-prompt.md). Fill in:
- `PROFILE_FILE`: absolute path to `$OUTPUT_DIR/profile/engineer-profile.md`
- `PATTERNS_DIR`: absolute path to `$OUTPUT_DIR/patterns/`
- `DECISIONS_FILE`: absolute path to `$OUTPUT_DIR/decisions/tech-decisions.md`
- `BRAIN_NAME`: from config
- `SCOPE`: from config (`hybrid`, `global`, or `local`)

**Resolve memory paths BEFORE spawning this agent:**

**IMPORTANT:** Claude Code has NO global memory directory (`~/.claude/memory/` does not exist). Global identity must go to `~/.claude/CLAUDE.md` which IS loaded in every session.

```bash
# Global: ~/.claude/CLAUDE.md (loaded in every Claude Code session)
GLOBAL_CLAUDE_MD="$HOME/.claude/CLAUDE.md"

# Local (project-specific) memory directory
LOCAL_MEMORY_DIR=$(ls -d ~/.claude/projects/*/memory/ 2>/dev/null | head -1)
# If not found, create it in the current project's memory path
if [ -z "$LOCAL_MEMORY_DIR" ]; then
  # The project hash is derived from the CWD
  LOCAL_MEMORY_DIR="$HOME/.claude/projects/$(pwd | sed 's/[\/\\:]/-/g' | sed 's/^-//')/memory"
  mkdir -p "$LOCAL_MEMORY_DIR"
fi
```

Pass the resolved paths to the agent — **all scopes need both paths**:
- `hybrid`: pass both `GLOBAL_CLAUDE_MD` and `LOCAL_MEMORY_DIR` — writes local files + appends to global
- `global`: pass both `GLOBAL_CLAUDE_MD` and `LOCAL_MEMORY_DIR` — writes local files + appends to global
- `local`: pass only `LOCAL_MEMORY_DIR` — writes local files only, no global changes

**Note:** Even `global` scope writes local memory files (detailed patterns/decisions) in addition to the global CLAUDE.md summary. The `global` label means the identity section also goes global, not that local files are skipped.

## Step 7: Verify & Report

After all phases complete:

1. **Cancel ALL cron jobs** — `CronDelete` for both `HARVEST_CRON_ID` and `CATEGORIZE_CRON_ID`
2. **Run verification script:**
   ```bash
   $PYTHON_CMD <SKILL_DIR>/scripts/verify.py "$WORK_DIR" "$OUTPUT_DIR"
   ```
   If Python was unavailable (preflight fallback), skip this step. If verify.py reports failures, fix them before reporting success.
3. Verify Claude memory files were written
4. Update `progress.md` to show 100% completion

**The Stop hook will block the session from ending if:**
- `engineer-profile.md` doesn't exist
- `progress.md` still has unchecked `[ ]` items

Report to the user:

```
BUILD COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  second-brain/                        — your full knowledge base
  second-brain/profile/engineer-profile.md — "<Brain Name>" engineer DNA
  second-brain/patterns/               — engineering patterns (8 categories)
  second-brain/philosophy/             — product thinking & workflow patterns
  second-brain/playbooks/              — debugging & scaling playbooks

  Memory scope: <hybrid/global/local>
  Global identity: ~/.claude/CLAUDE.md — core identity (loads everywhere)
  Local memory: ~/.claude/projects/... — repo patterns (loads in project)

  Repos analyzed: <list of repo IDs>
  Commits analyzed: <N total> (<per-repo breakdown>)
  Artifacts analyzed: <N files> (design specs, planning docs, project instructions)
  Patterns found: <count>
  Categories covered: <count>/12

  Hooks enforced: path validation, scratchpad structure, batch naming
  Verification: verify.py passed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Error Recovery

- **Agent fails mid-batch**: Scratchpad file has partial progress. On resume, count `## Commit:` headers — if fewer than expected, re-run from the last recorded commit hash. The harvest agent checks for existing entries before re-analyzing.
- **Context compresses**: PreCompact hook fires — reminds to re-read `$WORK_DIR/config.md` and `progress.md` to restore state.
- **Large diffs (>500 lines)**: Agents fall back to `git show --stat` + selective inspection. Binary files are skipped.
- **Empty categories**: Categories with <3 findings get "No significant patterns detected." Phase 3 handles gracefully — Brain Builder skips missing/empty category files.
- **>5000 commits**: Batch size increased to 50 (user confirmed in Step 0).
- **Merge commits**: Agents use `git show --stat` first. If empty, log as "Empty merge." If has changes, analyze selectively.
- **Cron job cleanup**: Cancel ALL cron jobs on BOTH success and failure paths using `CronDelete`.
- **Missing category file**: Re-spawn just that category agent rather than re-running all of Phase 2.
- **Hook blocks Write**: If PreToolUse hook blocks a write (relative path or missing REPO_ID), fix the path and retry. Do not bypass the hook.
- **Stop hook blocks exit**: If the Stop hook prevents session end, check what's missing (profile? unchecked progress items?) and complete it.
