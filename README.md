# Build Second Brain

A Claude Code plugin that analyzes any git repository **commit-by-commit** using parallel agent teams to extract your engineering patterns, architecture decisions, debugging approaches, and coding philosophy — then builds a structured **second brain** knowledge base with a personalized engineer profile.

> Your git history is a time machine of your thinking. Every commit answers: *Why did you change this architecture? Why did you add caching here? Why did you split this service?*
> This plugin reverse-engineers your engineering brain from those answers.

## What It Does

```
Phase 1: HARVEST ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Parallel agent teams analyze every single commit
  5-6 agents working simultaneously
  Findings written to scratchpad files (never lost)

Phase 2: CATEGORIZE ━━━━━━━━━━━━━━━━━━━━━━━━
  10 specialist agents organize findings:
  Architecture | Tech Stack | Debugging | Scaling
  Security | Data Modeling | Code Style | Refactoring
  Integration | Error Handling

Phase 3: SYNTHESIZE ━━━━━━━━━━━━━━━━━━━━━━━━
  Brain Builder → creates knowledge base
  Profile Generator → creates your engineer DNA
  Memory Injector → Claude now thinks like you
```

## Install

```bash
claude plugin add github.com/boparaiamrit/build-second-brain
```

## Usage

Navigate to any git repository and run:

```
/build-second-brain
```

The skill will ask for:
1. **Repo path** — path to the git repo to analyze
2. **Brain name** — what to call your brain (e.g., "Amrit's Brain", "Komal's Brain")

Then it runs all three phases automatically with maximum parallelism.

## What You Get

### 1. Structured Knowledge Base

```
second-brain/
├── profile/
│   └── engineer-profile.md          # Your engineer DNA
├── patterns/
│   ├── architecture-patterns.md     # System design patterns
│   ├── scaling-patterns.md          # How you handle growth
│   ├── debugging-patterns.md        # How you diagnose bugs
│   ├── security-patterns.md         # Auth & validation approach
│   ├── data-modeling-patterns.md    # Schema & migration patterns
│   ├── integration-patterns.md      # API & service connections
│   ├── error-handling-patterns.md   # Retry & resilience patterns
│   └── refactoring-patterns.md      # Cleanup patterns
├── decisions/
│   └── tech-decisions.md            # Every tech choice with reasoning
├── conventions/
│   └── code-style.md                # Naming & structure conventions
├── evolution/
│   └── architecture-evolution.md    # How the system evolved over time
├── playbooks/
│   ├── debugging-playbook.md        # Step-by-step debugging guide
│   └── scaling-playbook.md          # Step-by-step scaling guide
└── raw/
    ├── commit-log.md                # Annotated commit history
    └── statistics.md                # Numbers breakdown
```

### 2. Engineer Profile

A single document that captures your engineering DNA:

- **Core Philosophy** — your fundamental beliefs about software
- **Tech Stack DNA** — your go-to technology choices
- **Architecture Fingerprint** — how you structure systems
- **Debugging Style** — your step-by-step diagnostic process
- **Decision Patterns** — when faced with X, you choose Y because Z
- **Non-Negotiables** — things you ALWAYS or NEVER do
- **Evolution** — how your thinking changed over time

### 3. Claude Memory Injection

Three memory files written to your Claude Code memory directory so every future session already knows how you think:

- `second-brain-profile.md` — your identity and defaults
- `second-brain-patterns.md` — patterns Claude should follow
- `second-brain-decisions.md` — decision-making rules

## How It Works

### Phase 1: HARVEST (Agent Teams)

- Gets all commits chronologically via `git log --reverse`
- Splits into batches of 20 commits
- Spawns 5-6 parallel teammates via Claude Code Agent Teams
- Each teammate claims batches, analyzes commits via `git show`, writes findings to scratchpad files
- **Every finding is written to disk immediately** — nothing is kept only in memory

**What gets extracted from each commit:**
- What changed and why (inferred from diff + message)
- Patterns detected (e.g., "moved sync operation to async worker")
- Decisions made (e.g., "chose Redis over DB polling")
- Problems solved (e.g., "fixed race condition in queue worker")
- Category tags for Phase 2 filtering

### Phase 2: CATEGORIZE (10 Parallel Agents)

- An indexer script splits scratchpad findings by category tag
- 10 specialist agents run in parallel — one per knowledge category
- Each reads only its own pre-filtered content (~1/10th of total)
- Produces organized category files with patterns, principles, evolution, and key decisions

### Phase 3: SYNTHESIZE (3 Sequential Agents)

1. **Brain Builder** — creates the `second-brain/` directory with all pattern files, playbooks, and raw data
2. **Profile Generator** — creates the engineer profile document
3. **Memory Injector** — writes Claude memory files for future sessions

## Features

- **Every commit analyzed** — zero skipped (merge/empty commits are logged)
- **Maximum parallelism** — Agent Teams with 5-6 teammates, 10 parallel category agents
- **Crash-proof** — scratchpad files persist on disk; resume from where you left off
- **Large diff handling** — commits with >500 lines fall back to `git show --stat` + selective inspection
- **Progress tracking** — real-time progress via cron monitor
- **Resumable** — interrupted builds pick up from the last completed batch
- **Configurable brain name** — personalize for any engineer

## Requirements

- Claude Code with Agent Teams support (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)
  - Falls back to wave-based subagents if teams are unavailable
- Git repository with local access (private repos work fine — no GitHub API needed)
- Python 3 (for the indexer script)

## Token Estimates

For a 1000-commit repo:
- Phase 1 (Harvest): ~2M-5M tokens across all agents
- Phase 2 (Categorize): ~500K tokens
- Phase 3 (Synthesize): ~200K tokens
- **Total: ~3M-6M tokens**

## Plugin Structure

```
build-second-brain/
├── .claude-plugin/
│   └── plugin.json                          # Plugin manifest
├── skills/
│   └── build-second-brain/
│       ├── SKILL.md                         # Main orchestrator
│       ├── references/
│       │   ├── harvest-agent-prompt.md      # Phase 1 agent prompt
│       │   ├── category-agent-prompt.md     # Phase 2 agent prompt
│       │   ├── brain-builder-prompt.md      # Phase 3 agent 1
│       │   ├── profile-generator-prompt.md  # Phase 3 agent 2
│       │   ├── memory-injector-prompt.md    # Phase 3 agent 3
│       │   └── progress-template.md         # Progress tracking
│       └── scripts/
│           └── indexer.py                   # Category indexer
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-03-13-build-second-brain-design.md
├── README.md
└── LICENSE
```

## Contributing

Contributions welcome! Feel free to open issues or PRs.

## License

MIT

## Author

**Amritpal Singh** — [@boparaiamrit](https://github.com/boparaiamrit)

Built with [Claude Code](https://claude.ai/claude-code)
