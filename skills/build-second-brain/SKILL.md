---
name: build-second-brain
description: >
  Analyze a git repository commit-by-commit from the very first commit using maximum parallel agents
  to extract engineering patterns, architecture decisions, debugging approaches, scaling strategies,
  and coding conventions — then build a structured "second brain" knowledge base with a personalized
  engineer profile and Claude memory injection. Use this skill when the user mentions "second brain",
  "analyze my repo", "extract my patterns", "learn from my commits", "build my brain", "reverse engineer
  my thinking", "learn how I code", "analyze git history", or wants to capture their engineering
  decision-making from a codebase. Also trigger when the user wants to create an engineer profile,
  extract architecture patterns from commits, or build a knowledge base from code history.
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
  PreCompact:
    - command: "bash -c 'echo Context compacting — all findings should already be in scratchpad files on disk.'"
---

# Build Second Brain

Extract an engineer's thinking patterns, architecture decisions, and coding philosophy from their git history — commit by commit, using maximum parallel agents — and build a structured knowledge base + engineer profile.

## Overview

This skill runs a three-phase pipeline:
1. **HARVEST** — Parallel agents analyze every commit, writing findings to scratchpad files
2. **CATEGORIZE** — 10 category agents organize findings into knowledge domains
3. **SYNTHESIZE** — Build the final second brain directory, engineer profile, and Claude memory

Every agent writes to disk immediately. Nothing is kept only in memory. If context compresses or an agent crashes, all work persists in scratchpad files and can be resumed.

## Step 0: Gather Inputs

Ask the user for two things (or accept as arguments):

1. **Repo path** — "What's the path to the git repo you want to analyze?"
2. **Brain name** — "What should we name this brain?" (default: "Second Brain")
   - Examples: "Amrit's Brain", "Komal's Brain", "DevTeam Brain"

Then run preflight checks:

```bash
cd <repo_path> && git rev-list --count HEAD
```

Report the commit count to the user:
> "This repo has **X commits**. I'll split them into **Y batches of 20** and use parallel agents to analyze every single one. This will produce a comprehensive knowledge base. Proceed?"

Wait for confirmation before continuing.

## Step 1: Initialize

Create the working directory structure and config:

```bash
mkdir -p .second-brain/scratchpad .second-brain/indexed .second-brain/categories
```

Write `.second-brain/config.md`:
```markdown
# Second Brain Config
Brain Name: <user's chosen name>
Repo Path: <repo path>
Total Commits: <N>
Batch Size: 20
Total Batches: <ceil(N/20)>
Started: <timestamp>
```

### Resume Check

Before initializing, check if `.second-brain/progress.md` already exists. If it does:
> "Found existing progress — X of Y batches completed. Resume from where we left off? (y/n)"

If resuming, skip to the appropriate phase and only process incomplete work.

## Step 2: Get All Commits

```bash
cd <repo_path> && git log --format="%H|%s|%ai" --reverse > .second-brain/commits.txt
```

Split into batches. Each batch is 20 consecutive commits. Calculate batch boundaries:
- Batch 001: commits 1-20
- Batch 002: commits 21-40
- etc.

Write initial `progress.md` (see [references/progress-template.md](references/progress-template.md)).

## Step 3: Phase 1 — HARVEST

This is the most critical phase. Every commit gets analyzed.

### Agent Teams Mode (preferred)

Try to use Agent Teams for self-balancing workload:

1. Create a team with 5 teammates
2. Create one task per batch in the shared task list
3. Each teammate claims batches, processes them, and moves to the next

The prompt for each teammate is in [references/harvest-agent-prompt.md](references/harvest-agent-prompt.md). Read it and use it as the agent prompt, filling in:
- `REPO_PATH`: the repo path
- `BATCH_NUMBERS`: "claim tasks from the shared task list"
- `SCRATCHPAD_DIR`: the `.second-brain/scratchpad/` path

### Fallback Mode (if teams unavailable)

If TeamCreate fails or is unavailable, fall back to wave-based background subagents:

1. Spawn 5 background agents per wave
2. Each agent gets statically assigned batches (agent 1 gets batches 1,6,11,...; agent 2 gets 2,7,12,...; etc.)
3. Wait for all 5 to complete before spawning next wave
4. Use the same harvest agent prompt from [references/harvest-agent-prompt.md](references/harvest-agent-prompt.md)

### Progress Monitoring

After launching harvest agents, set up a progress monitor:

```
CronCreate: every 2 minutes
Prompt: "Count files in .second-brain/scratchpad/ matching batch-*.md.
         Read .second-brain/config.md for total batches.
         Calculate percentage. Update .second-brain/progress.md Phase 1 section."
```

Wait for all harvest agents to complete. Verify: the number of `batch-*.md` files in scratchpad equals the total batch count.

## Step 4: Phase 1.5 — INDEX

Before spawning category agents, run the indexer to split scratchpad findings by category tag. This prevents any category agent from needing to read all scratchpad files (which would overflow context).

Run the indexer script:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/build-second-brain/scripts/indexer.py" .second-brain/scratchpad .second-brain/indexed
```

This reads every `batch-*.md` file, finds `### Category Tags` sections, and splits each commit's findings into the appropriate `<category>-raw.md` file in the `indexed/` directory.

**If Python is unavailable**, do it inline: read each scratchpad file, grep for category tags, and write findings to the appropriate indexed file. The categories are:
`architecture`, `tech-stack`, `debugging`, `scaling`, `security`, `data-modeling`, `code-style`, `refactoring`, `integration`, `error-handling`

## Step 5: Phase 2 — CATEGORIZE

Spawn 10 background subagents in parallel — one per knowledge category.

Each agent's prompt is templated from [references/category-agent-prompt.md](references/category-agent-prompt.md). Fill in:
- `CATEGORY_NAME`: the category (e.g., "Architecture")
- `CATEGORY_SLUG`: the slug (e.g., "architecture")
- `INDEXED_FILE`: path to `.second-brain/indexed/<slug>-raw.md`
- `OUTPUT_FILE`: path to `.second-brain/categories/<slug>.md`
- `BRAIN_NAME`: from config

The 10 categories and what each agent extracts:

| Category | Slug | Extracts |
|----------|------|----------|
| Architecture | `architecture` | System structure, module boundaries, service splits, folder organization |
| Tech Stack | `tech-stack` | Library/framework/tool choices and reasoning |
| Debugging | `debugging` | Bug patterns, root causes, diagnostic steps, fixes |
| Scaling | `scaling` | Queues, workers, caching, async patterns, load handling |
| Security | `security` | Auth, validation, sanitization, access control, secrets |
| Data Modeling | `data-modeling` | Schema design, migrations, relationships, indexes, queries |
| Code Style | `code-style` | Naming, file structure, import patterns, code organization |
| Refactoring | `refactoring` | What was messy, why cleaned, before/after patterns |
| Integration | `integration` | External APIs, webhooks, third-party services |
| Error Handling | `error-handling` | Retries, fallbacks, circuit breakers, logging, monitoring |

Wait for all 10 to complete. Verify all category files exist.

## Step 6: Phase 3 — SYNTHESIZE

Run 3 agents **sequentially** (each depends on the previous):

### Agent 1: Brain Builder

Read the prompt from [references/brain-builder-prompt.md](references/brain-builder-prompt.md).

This agent reads all 10 category files and creates the final `second-brain/` directory:

```
second-brain/
├── README.md
├── profile/           (created by Agent 2)
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

### Agent 2: Profile Generator

Read the prompt from [references/profile-generator-prompt.md](references/profile-generator-prompt.md).

This agent reads all category files + config (for brain name) and generates:
`second-brain/profile/engineer-profile.md`

The profile captures the engineer's DNA: philosophy, tech preferences, architecture fingerprint, debugging style, decision patterns, and evolution narrative.

### Agent 3: Memory Injector

Read the prompt from [references/memory-injector-prompt.md](references/memory-injector-prompt.md).

This agent reads the profile + key patterns and writes Claude memory files so future sessions already know how the engineer thinks.

It writes to the current project's Claude memory directory:
- `second-brain-profile.md` (type: user)
- `second-brain-patterns.md` (type: feedback)
- `second-brain-decisions.md` (type: feedback)
- Updates `MEMORY.md` index

## Step 7: Verify & Report

After all phases complete:

1. Verify all expected output files exist in `second-brain/`
2. Verify the engineer profile is non-empty and substantive
3. Verify Claude memory files were written
4. Update `progress.md` to show 100% completion
5. Cancel the progress monitor cron job

Report to the user:

```
BUILD COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  second-brain/                        — your full knowledge base
  second-brain/profile/engineer-profile.md — "<Brain Name>" engineer DNA
  second-brain/patterns/               — X patterns across 10 categories
  second-brain/playbooks/              — debugging & scaling playbooks
  .claude/memory/                      — Claude now thinks like you

  Commits analyzed: <N>
  Patterns found: <count>
  Categories covered: <count>/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Error Recovery

- **Agent fails mid-batch**: Scratchpad file has partial progress. On resume, count `## Commit:` headers in the file — if fewer than 20, re-run from the last recorded commit hash.
- **Context compresses**: All findings are on disk in scratchpad files. The PreCompact hook reminds of this.
- **Large diffs (>500 lines)**: Agents fall back to `git show --stat` + selective inspection. Binary files are skipped.
- **Empty categories**: Categories with <3 findings get "No significant patterns detected." Phase 3 handles gracefully.
- **>5000 commits**: Warn user and suggest increasing batch size to 50.
