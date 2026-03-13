# Build Second Brain — Skill Design Spec

## Overview

A Claude Code skill (`/build-second-brain`) that analyzes a git repository commit-by-commit from the very first commit, using maximum parallel agents, to extract engineering patterns, decisions, debugging approaches, and architectural thinking — then builds a structured "second brain" knowledge base and engineer profile.

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

### Phase 1: HARVEST — Agent Team Swarm

**Goal:** Extract raw findings from every single commit.

**Mechanism:** Agent Teams (`TeamCreate`)

- Orchestrator runs `git log --format="%H %s" --reverse` to get all commits chronologically
- Splits into batches of ~20 commits each
- Creates a shared task list with one task per batch
- Spawns 5-6 teammates (no worktree needed — `git show` is read-only and safe to run concurrently)
- Each teammate:
  1. Claims next available batch from the shared task list
  2. For each commit in the batch, runs `git show <hash>` to get the full diff
  3. **Large diff guard:** If `git show` output exceeds 500 lines, use `git show --stat <hash>` for overview + selectively examine key changed files. Skip binary files entirely.
  4. Extracts structured findings (see Extraction Template below)
  5. **Per-commit category tagging:** Tags each finding with its category (architecture, debugging, etc.) so Phase 2 agents can filter efficiently
  6. Writes ALL findings to `.second-brain/scratchpad/batch-NNN.md`
  7. Marks batch task complete, claims next batch
  8. Repeats until no batches remain

**Extraction Template (per commit):**

```markdown
## Commit: <hash_short>
Message: <commit message>
Date: <date>
Files Changed: <list>

### What Changed
<description of code changes>

### Why It Changed (Inferred)
<reasoning from diff + message>

### Patterns Detected
- <pattern name>: <description>

### Decisions Made
- <decision>: <reasoning>

### Problems Solved
- <problem>: <solution applied>

### Category Tags
<architecture|tech-stack|debugging|scaling|security|data-modeling|code-style|refactoring|integration|error-handling>
```

**Scratchpad Rules (injected into every agent prompt):**

```
SCRATCHPAD RULES — NON-NEGOTIABLE:
1. Write ALL findings to your assigned scratchpad file
2. Write AFTER analyzing each commit — do NOT batch in memory
3. Over-capture: if unsure, write it anyway
4. NEVER rely on context window to remember findings
5. Before finishing, re-read your scratchpad file to verify completeness
6. Include commit hashes so findings are traceable
```

**Teammate Count:** 5-6 (optimal per Claude Code team guidance — beyond 6, coordination overhead exceeds benefits).

**Batch Size:** 20 commits per batch. For 1000 commits = 50 batches. Each teammate processes ~8-10 batches (~160-200 commits).

### Phase 2: CATEGORIZE — 10 Parallel Subagents

**Goal:** Organize raw findings into 10 knowledge categories.

**Mechanism:** Background subagents (`run_in_background: true`)

After Phase 1 completes, spawn 10 subagents in parallel (one per category):

| # | Agent | Extracts |
|---|-------|----------|
| 1 | Architecture | System structure, module boundaries, service splits, folder organization |
| 2 | Tech Stack | Library/framework/tool choices and reasoning |
| 3 | Debugging | Bug patterns, root causes, diagnostic steps, fixes |
| 4 | Scaling | Queues, workers, caching, async patterns, load handling |
| 5 | Security | Auth, validation, sanitization, access control, secrets |
| 6 | Data Modeling | Schema design, migrations, relationships, indexes, queries |
| 7 | Code Style | Naming, file structure, import patterns, code organization |
| 8 | Refactoring | What was messy, why cleaned, before/after patterns |
| 9 | Integration | External APIs, webhooks, third-party services |
| 10 | Error Handling | Retries, fallbacks, circuit breakers, logging, monitoring |

**Pre-categorization step (runs before category agents):**
The orchestrator runs a lightweight indexer that scans all scratchpad files and splits findings by category tag into per-category intermediate files at `.second-brain/indexed/<category>-raw.md`. This way each category agent only reads its own relevant content (~1/10th of total), staying well within context limits.

Each category agent:
1. Reads its pre-indexed file from `.second-brain/indexed/<category>-raw.md` (NOT all scratchpad files)
2. Groups findings into patterns, rules, and evolution timeline
3. If its indexed file is still too large (>2000 lines), processes in chunks with incremental summarization
4. Writes organized output to `.second-brain/categories/<category>.md`
5. If a category has fewer than 3 findings, notes "No significant patterns detected" — Phase 3 agents handle sparse categories gracefully
6. Persists key findings to agent memory (`memory: project`)

**Category File Structure:**

```markdown
# <Category Name>

## Patterns Found
### Pattern 1: <name>
- Description: <what>
- Evidence: commits <hash1>, <hash2>, ...
- Rule: <if X then Y>

## Principles Inferred
- <principle with reasoning>

## Evolution Over Time
- Early: <how it started>
- Middle: <how it changed>
- Late: <current approach>

## Key Decisions
- <decision>: <why> (commit <hash>)
```

### Phase 3: SYNTHESIZE — 3 Sequential Subagents

**Goal:** Build the final second brain output.

**Agent 1: Brain Builder**
- Reads all 10 category files
- Creates the `second-brain/` directory structure
- Writes organized pattern files, playbooks, decision logs
- Writes `evolution/architecture-evolution.md` (timeline of how system grew)
- Writes `raw/commit-log.md` (annotated commit history)
- Writes `raw/statistics.md` (numbers breakdown)

**Agent 2: Profile Generator**
- Reads all 10 category files
- Reads brain name from `.second-brain/config.md`
- Generates `second-brain/profile/engineer-profile.md` containing:
  - Core philosophy
  - Tech stack DNA
  - Architecture fingerprint
  - Debugging style (step-by-step)
  - Decision patterns (when X, chooses Y because Z)
  - Evolution narrative

**Agent 3: Memory Injector**
- Reads the profile + key patterns
- Resolves memory path: uses the current project's Claude memory directory (determined by `~/.claude/projects/` + sanitized working directory path). If the directory doesn't exist, creates it.
- Writes Claude memory files:
  - `second-brain-profile.md` — core engineer profile (with proper frontmatter: name, description, type: user)
  - `second-brain-patterns.md` — key patterns to follow (type: feedback)
  - `second-brain-decisions.md` — decision-making rules (type: feedback)
- Creates or updates `MEMORY.md` index in the memory directory with links to all three files

---

## Scratchpad & File System

### Directory Structure During Execution

```
.second-brain/
├── config.md                          ← Brain name, repo path, settings
├── progress.md                        ← Phase/batch completion tracking
├── scratchpad/                        ← Phase 1 output (temporary)
│   ├── batch-001-commits-1-20.md
│   ├── batch-002-commits-21-40.md
│   └── ... (one per batch)
├── indexed/                           ← Pre-categorized splits (Phase 1.5)
│   ├── architecture-raw.md
│   ├── tech-stack-raw.md
│   ├── debugging-raw.md
│   └── ... (one per category)
└── categories/                        ← Phase 2 output (temporary)
    ├── architecture.md
    ├── tech-stack.md
    ├── debugging.md
    ├── scaling.md
    ├── security.md
    ├── data-modeling.md
    ├── code-style.md
    ├── refactoring.md
    ├── integration.md
    └── error-handling.md
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

**Progress tracking mechanism:** The orchestrator (not teammates) updates `progress.md` by detecting scratchpad file existence. Each completed batch produces a file (`batch-NNN.md`). The orchestrator/cron polls for these files and updates progress. This avoids race conditions from multiple agents writing to the same progress file.

`progress.md` structure:

```markdown
# Second Brain Build Progress
Brain Name: <name>
Repo: <path>
Total Commits: <N>
Batch Size: 20
Total Batches: <N/20>

## Phase 1: Harvest
- [x] batch-001 (commits 1-20)
- [x] batch-002 (commits 21-40)
- [ ] batch-003 (commits 41-60)
...

## Phase 2: Categorize
- [ ] architecture
- [ ] debugging
...

## Phase 3: Synthesize
- [ ] brain-builder
- [ ] profile-generator
- [ ] memory-injector
```

### Progress Monitor Loop

```
CronCreate: every 2 minutes
  → Read .second-brain/progress.md
  → Count completed vs total
  → Report percentage to user
```

### Resume Capability

On skill invocation, check for existing `.second-brain/progress.md`:
- If found: offer to resume from last completed step
- Skip all completed batches/categories
- Only process remaining work

### Hooks

```yaml
hooks:
  Stop:
    - command: "bash -c 'test -f second-brain/profile/engineer-profile.md && echo ok || (echo \"Profile not generated\" >&2 && exit 2)'"
  PreCompact:
    - command: "bash -c 'echo \"Context compacting. Ensure all findings written to scratchpad files.\"'"
```

### Skill Frontmatter

```yaml
---
name: build-second-brain
description: >
  Analyze a git repository commit-by-commit using parallel agent teams
  to extract engineering patterns, decisions, and build a structured
  second brain knowledge base with engineer profile.
allowed-tools:
  - Agent
  - TeamCreate
  - TeamDelete
  - SendMessage
  - TodoWrite
  - CronCreate
  - CronDelete
  - CronList
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
  - AskUserQuestion
  - TaskOutput
hooks:
  Stop:
    - command: "bash -c 'test -f second-brain/profile/engineer-profile.md && echo ok || (echo Profile not generated >&2 && exit 2)'"
  PreCompact:
    - command: "bash -c 'echo Context compacting — flush findings to scratchpad'"
---
```

---

## Skill Invocation UX

### Trigger

```
/build-second-brain
```

### User Prompts

1. **Repo path:** "What's the path to the git repo?" (or pass as argument)
2. **Brain name:** "What should we name this brain?" (default: "Second Brain")
3. **Confirmation:** "This repo has X commits. I'll create Y batches and use agent teams for parallel processing. Proceed?"

### Execution Output

```
Phase 1: HARVEST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Creating harvest team with 5 teammates...
  53 batch tasks created
  Teammates claiming batches...
  Progress: 10/53 batches ██░░░░░░░░ 19%
  Progress: 30/53 batches █████░░░░░ 57%
  Progress: 53/53 batches ██████████ 100%
  Phase 1 complete: 1047 commits harvested

Phase 2: CATEGORIZE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Spawning 10 category agents...
  ✓ code-style complete
  ✓ debugging complete
  ...
  Phase 2 complete: 10 category files written

Phase 3: SYNTHESIZE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Brain directory built
  ✓ Engineer profile generated: "Amrit's Brain"
  ✓ Claude memory files injected

BUILD COMPLETE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  second-brain/ — your full knowledge base
  second-brain/profile/engineer-profile.md — your engineer DNA
  .claude/memory/ — Claude now thinks like you
```

---

## Error Handling

- **Agent fails mid-batch:** Scratchpad file serves as partial progress. On resume, if a batch file exists but has fewer than 20 commit sections, the batch is re-run starting from the last recorded commit hash. If no file exists, the entire batch is retried.
- **Context compresses:** PreCompact hook warns. Scratchpad files persist on disk. Agent memory persists across resets.
- **Repo too large:** Skill warns if >5000 commits and suggests increasing batch size to 50.
- **Large diffs:** If `git show` output exceeds 500 lines, agent falls back to `git show --stat` + selective file inspection. Binary files are always skipped.
- **Empty commits / merge commits:** Accounted for — logged with "no diff" notation but not deeply analyzed. Success criteria counts them as "accounted for" not "analyzed."
- **Empty categories:** If a category agent finds <3 findings, it writes "No significant patterns detected." Phase 3 handles these gracefully.
- **Permission denied:** Skill uses `allowed-tools` to pre-authorize needed tools.

## Constraints

- **Agent Teams mode (preferred):** Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Teammates self-balance workload via shared task list.
- **Fallback mode (if teams unavailable):** Spawns background subagents in waves of 5. Each wave gets 5 batches assigned statically. Orchestrator waits for all 5 to complete before spawning next wave. Scratchpad file format is identical — Phase 2 and 3 work the same regardless of mode. The skill auto-detects which mode to use by attempting `TeamCreate` and falling back on failure.
- Private repos only need local git access — no GitHub API required
- **Token estimate:** ~2,000-5,000 tokens per commit (diff + analysis). For 1000 commits: ~2M-5M input tokens across all agents. Phase 2 adds ~500K. Phase 3 adds ~200K. Total estimate: ~3M-6M tokens.

## Success Criteria

1. Every commit in the repo is accounted for — commits with diffs are fully analyzed, merge/empty commits are logged
2. All 10 knowledge categories have organized findings
3. Engineer profile accurately reflects patterns from the codebase
4. Claude memory files enable future sessions to think like the engineer
5. Process is resumable if interrupted
6. Scratchpad files provide full audit trail
