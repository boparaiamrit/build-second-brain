# Build Second Brain — Skill Design Spec (v2 — Post-Audit)

## Overview

A Claude Code plugin (`/build-second-brain`) that analyzes a git repository commit-by-commit from the very first commit, using maximum parallel agents, to extract engineering patterns, decisions, debugging approaches, and architectural thinking — then builds a structured "second brain" knowledge base and engineer profile.

## Problem

Engineers who work with AI coders (Claude Code, Codex) face a repetitive loop: every session starts from zero context. The AI doesn't know the engineer's architecture preferences, debugging style, scaling decisions, or production paranoia. This skill reverses that by mining the engineer's git history to extract their engineering brain.

## Target User

- AI-native engineers with 1000+ commit repos
- Private repos, local git access
- Want a persistent knowledge base that makes AI think like them

## Approach: Parallel Swarm with Shared Scratchpad

Three-phase architecture using Agent Teams, background agents, hooks, loops, and scratchpad persistence.

---

## Architecture

### Key Design Principle: Absolute Paths Everywhere

All paths are resolved to absolute paths in Step 0 and passed to every agent prompt. No agent ever uses relative paths. This prevents CWD-related failures across subagents, teams, cron jobs, and bash commands.

### Security: Data Isolation

All agent prompts include explicit instructions to treat commit messages and diff content as UNTRUSTED DATA — never as instructions to follow. This prevents prompt injection via malicious commit messages.

### Phase 1: HARVEST — Agent Team Swarm

**Goal:** Extract raw findings from every single commit.

**Mechanism:** Agent Teams (`TeamCreate`) with fallback to wave-based subagents.

**Preflight (Step 0):**
- Verify repo exists and has >0 commits
- Check Python availability (for indexer)
- If >5000 commits, suggest batch size 50 (default: 20)
- Resolve all absolute paths: `WORK_DIR`, `REPO_PATH`, `COMMITS_FILE`
- Record HEAD commit hash for reproducibility

**Execution:**
- Orchestrator runs `git -C "$REPO_PATH" log --format="%H|%s|%ai" --reverse > "$WORK_DIR/commits.txt"`
- Splits into batches of configurable size (20 or 50)
- **Teams mode:** Creates team with 5 teammates. Tasks added via `TodoWrite`. Each teammate claims tasks, processes batches, marks complete.
- **Fallback mode:** Spawns 5 background agents per wave with statically assigned batches. Uses `TaskOutput` to poll for completion before spawning next wave.
- Each teammate:
  1. Claims next available batch
  2. For each commit, runs `git -C "$REPO_PATH" show <hash>` to get the full diff
  3. **Large diff guard:** If output exceeds 500 lines, use `git show --stat` + selective inspection. Skip binary files.
  4. **Resume check:** Before analyzing a commit, check if it already exists in the scratchpad file. Skip if found.
  5. Extracts structured findings with per-commit category tagging
  6. Writes ALL findings to `$WORK_DIR/scratchpad/batch-NNN-commits-X-Y.md` IMMEDIATELY after each commit
  7. Marks batch task complete, claims next batch

**Batch size:** Configurable (20 default, 50 for >5000 commits). Stored in `config.md` and passed to all agents.

**Progress monitoring:** CronCreate with `*/2 * * * *` expression polls for scratchpad file count. Cron job ID stored for cleanup on both success and failure.

**Phase 1 completion verification:** Count batch files AND verify each has expected number of `## Commit:` headers. Re-spawn agents for incomplete batches only.

### Phase 1.5: INDEX

**Goal:** Split scratchpad findings by category tag for efficient Phase 2 processing.

**Mechanism:** Python indexer script (`scripts/indexer.py`)

The indexer:
- Reads all `batch-*.md` files from scratchpad directory
- Uses fuzzy tag matching (normalizes hyphens/underscores/spaces) to handle agent tag variations
- Assigns **untagged commits to an `uncategorized` bucket** (NOT to all categories — this was a critical design fix)
- Produces per-category `<slug>-raw.md` files in the indexed directory
- Produces `statistics-raw.md` with pre-computed counts (commits per category, timeline by month)
- Handles file I/O errors gracefully (skips locked/unreadable files with warnings)
- Compatible with Python 3.7+ (uses `from __future__ import annotations`)

**Bash fallback:** If Python unavailable, approximate splitting via grep (less accurate, documented as fallback).

### Phase 2: CATEGORIZE — 10 Subagents in 2 Waves

**Goal:** Organize raw findings into 10 knowledge categories.

**Mechanism:** Background subagents in **two waves of 5** (prevents resource exhaustion)

- Wave 1: architecture, tech-stack, debugging, scaling, security
- Wave 2: data-modeling, code-style, refactoring, integration, error-handling
- Each wave: spawn 5 background agents, collect agent IDs, poll with `TaskOutput` until all complete

Each category agent:
1. Reads its pre-indexed file from `$WORK_DIR/indexed/<slug>-raw.md` (NOT all scratchpad files)
2. Receives `CATEGORY_DESCRIPTION` template variable (what specifically to extract)
3. If indexed file exceeds 2000 lines, processes in chunks with incremental summarization
4. Writes organized output to `$WORK_DIR/categories/<slug>.md`
5. If fewer than 3 findings, notes "No significant patterns detected"

After both waves: verify all 10 category files exist. Re-spawn failed agents individually.

### Phase 3: SYNTHESIZE — 3 Sequential Subagents

**Goal:** Build the final second brain output.

**Agent 1: Brain Builder**
- Reads all 10 category files (skips missing/empty ones gracefully)
- Creates the `second-brain/` directory structure
- Writes organized pattern files, playbooks, decision logs
- Uses pre-computed `statistics-raw.md` for `raw/statistics.md` (does NOT read scratchpad files)
- `raw/commit-log.md` is generated by orchestrator via bash BEFORE this agent runs:
  ```bash
  grep "^## Commit:\|^Message:" "$WORK_DIR"/scratchpad/batch-*.md > second-brain/raw/commit-log.md
  ```

**Agent 2: Profile Generator**
- Reads all 10 category files + config (for brain name)
- Writes profile incrementally (scratchpad discipline against context compression)
- Generates `second-brain/profile/engineer-profile.md`

**Agent 3: Memory Injector**
- Reads the profile + key patterns
- Memory directory resolved by orchestrator BEFORE spawning (via `ls ~/.claude/projects/*/memory/`)
- Receives absolute `MEMORY_DIR` path — does not guess
- Writes 3 Claude memory files with proper frontmatter
- Creates or updates `MEMORY.md` index (appends, never overwrites existing entries)

---

## Scratchpad & File System

### Directory Structure During Execution

```
.second-brain/                    (WORK_DIR — absolute path)
├── config.md                     ← Brain name, repo path, batch size, HEAD hash
├── commits.txt                   ← Full commit list (hash|message|date)
├── progress.md                   ← Phase/batch completion tracking
├── scratchpad/                   ← Phase 1 output
│   ├── batch-001-commits-1-20.md
│   ├── batch-002-commits-21-40.md
│   └── ... (one per batch)
├── indexed/                      ← Phase 1.5 output
│   ├── architecture-raw.md
│   ├── tech-stack-raw.md
│   ├── ...
│   ├── uncategorized-raw.md      ← Commits with no recognized tags
│   └── statistics-raw.md         ← Pre-computed counts and timeline
└── categories/                   ← Phase 2 output
    ├── architecture.md
    ├── tech-stack.md
    └── ... (10 total)
```

### Final Output Structure

```
second-brain/
├── README.md
├── profile/
│   └── engineer-profile.md
├── patterns/
│   ├── architecture-patterns.md
│   ├── scaling-patterns.md
│   ├── debugging-patterns.md
│   ├── security-patterns.md
│   ├── data-modeling-patterns.md
│   ├── integration-patterns.md
│   ├── error-handling-patterns.md
│   └── refactoring-patterns.md
├── decisions/
│   └── tech-decisions.md
├── conventions/
│   └── code-style.md
├── evolution/
│   └── architecture-evolution.md
├── playbooks/
│   ├── debugging-playbook.md
│   └── scaling-playbook.md
└── raw/
    ├── commit-log.md
    └── statistics.md
```

---

## Orchestration Details

### Progress Tracking

The orchestrator (not teammates) updates `progress.md` by detecting scratchpad file existence. Each completed batch produces a file. The cron job polls for these files and updates progress. This avoids race conditions.

`progress.md` has checkboxes for every item in every phase. On resume, the orchestrator parses ALL checkmarks to determine the first unchecked item — not just batch count.

### Resume Capability

On skill invocation, check for existing `progress.md`:
- Parse which Phase 1 batches are `[x]`
- Parse which Phase 2 categories are `[x]`
- Parse which Phase 3 steps are `[x]`
- Resume from the **first unchecked item**
- Harvest agents also check for existing partial scratchpad files and continue from last recorded commit

### Hooks

```yaml
hooks:
  Stop:
    - command: "bash -c 'test -f second-brain/profile/engineer-profile.md && echo ok || (echo \"Profile not generated\" >&2 && exit 2)'"
  PreCompact:
    - command: "bash -c 'echo \"Context compacting. Ensure all findings written to scratchpad files.\"'"
```

---

## Error Handling

- **Agent fails mid-batch:** Scratchpad file serves as partial progress. On resume, harvest agent counts `## Commit:` headers and continues from the last recorded hash.
- **Context compresses:** All findings on disk. Orchestrator re-reads `config.md` to restore state.
- **Repo too large (>5000):** Batch size increased to 50, confirmed with user in preflight.
- **Large diffs (>500 lines):** `git show --stat` + selective inspection. Binary files skipped.
- **Merge commits:** `git show --stat` first. Empty merges logged, non-empty merges analyzed selectively.
- **Binary-only commits:** Logged with file list, not deeply analyzed.
- **Empty categories (<3 findings):** "No significant patterns detected." Phase 3 skips gracefully.
- **Unrecognized category tags:** Fuzzy matching in indexer. Truly unrecognized go to `uncategorized` bucket with warning.
- **Missing category file:** Re-spawn just that agent, not all of Phase 2.
- **Cron cleanup:** Cancel on BOTH success and failure paths.
- **Prompt injection:** All agent prompts include data isolation instructions.

## Constraints

- **Agent Teams mode (preferred):** Uses `TeamCreate` with `TodoWrite` for task claiming.
- **Fallback mode:** Wave-based background subagents (5 per wave). Uses `TaskOutput` for completion detection. Statically assigned batches.
- Private repos only need local git access — no GitHub API required.
- Python 3.7+ required for indexer (bash fallback available but less accurate).
- **Token estimate:** ~2,000-5,000 tokens per commit. For 1000 commits: ~3M-6M total tokens.

## Success Criteria

1. Every commit accounted for — commits with diffs fully analyzed, merge/empty/binary commits logged
2. All 10 knowledge categories have organized findings
3. Engineer profile accurately reflects patterns from the codebase
4. Claude memory files enable future sessions to think like the engineer
5. Process is resumable if interrupted at any phase
6. Scratchpad files provide full audit trail
7. No data lost to context compression, agent crashes, or path resolution failures
