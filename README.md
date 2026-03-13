<p align="center">
  <h1 align="center">🧠 Build Second Brain</h1>
  <p align="center">
    <strong>Your git history is a goldmine of decisions, patterns, and philosophy.<br>This plugin mines all of it — so Claude already knows how you think.</strong>
  </p>
  <p align="center">
    Every commit. Every design spec. Every planning doc. Every CLAUDE.md.<br>
    Extracted, organized into 12 categories, and injected into Claude's memory.
  </p>
  <p align="center">
    <a href="#-quick-start"><img src="https://img.shields.io/badge/Get_Started-blue?style=for-the-badge" alt="Get Started"></a>
    <a href="https://boparaiamrit.github.io/build-second-brain/"><img src="https://img.shields.io/badge/Website-7c3aed?style=for-the-badge&logo=google-chrome&logoColor=white" alt="Website"></a>
    <a href="https://github.com/boparaiamrit/build-second-brain"><img src="https://img.shields.io/github/stars/boparaiamrit/build-second-brain?style=for-the-badge&color=gold" alt="Stars"></a>
    <a href="https://github.com/boparaiamrit/build-second-brain/blob/main/LICENSE"><img src="https://img.shields.io/github/license/boparaiamrit/build-second-brain?style=for-the-badge" alt="License"></a>
  </p>
  <p align="center">
    <a href="https://github.com/boparaiamrit"><img src="https://img.shields.io/badge/GitHub-boparaiamrit-181717?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://x.com/boparaiamrit"><img src="https://img.shields.io/badge/X-@boparaiamrit-000000?style=flat-square&logo=x" alt="X/Twitter"></a>
    <a href="https://github.com/sponsors/boparaiamrit"><img src="https://img.shields.io/badge/Sponsor-❤️-ea4aaa?style=flat-square" alt="Sponsor"></a>
  </p>
</p>

---

## 🌟 What is This?

**Build Second Brain** is a Claude Code plugin that analyzes your entire git history — **every single commit, design spec, planning doc, and project instruction** — using parallel agent teams to extract your engineering patterns, product thinking, planning philosophy, and architecture decisions. It builds a structured **second brain** knowledge base with a holistic builder profile.

> 💡 Your git history is a time machine of your thinking. Every commit answers: *Why did you change this?* Every design spec answers: *What trade-offs did you weigh?* Every planning doc answers: *How do you break down problems?* This plugin reverse-engineers your complete builder brain from those answers.

**It's not just a developer brain. It's the combined brain of a product thinker, architect, and engineer.**

---

### 💎 The Gem: Parallel Agent Swarm + Artifact Mining

> The most comprehensive approach to extracting engineering intelligence from code — parallel harvest, artifact mining, and memory injection.

**The Harvest Engine** spawns **5 parallel agent teammates** via Agent Teams — each gets a fresh context window, claims batches of commits, analyzes diffs, and writes findings to scratchpad files on disk immediately. Nothing is kept only in memory.

**Artifact Mining** goes beyond code — it reads design specs, planning docs, CLAUDE.md files, ADRs, PR templates, and GSD plans in **chronological order** to capture the hierarchy of your thinking. What you created first reveals what was foundational.

```
                    ╔═══════════════════════════════════╗
                    ║    🎯 ORCHESTRATOR (lean)           ║
                    ║  5 phases · 6 hooks · Progress      ║
                    ║  tracking · Crash recovery          ║
                    ╚════════════════╦══════════════════╝
                                    ║
                           Agent Teams spawning
           ┌────────────────────────┼────────────────────────┐
    ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐  ┌────▼────────┐
    │🔬 Harvest   │  │📐 Harvest   │  │⚙️ Harvest   │  │🔍 Harvest   │
    │ Agent 1     │  │ Agent 2     │  │ Agent 3     │  │ Agent 4-5   │
    │ Batch 1-3   │  │ Batch 4-6   │  │ Batch 7-9   │  │ Batch 10+   │
    │ Fresh ctx   │  │ Fresh ctx   │  │ Fresh ctx   │  │ Fresh ctx   │
    └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
           │                │                │                │
           ▼                ▼                ▼                ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              📁 Scratchpad Files (on disk)                   │
    │   batch-myapp-001.md  batch-myapp-002.md  artifacts-myapp.md│
    └──────────────────────────┬──────────────────────────────────┘
                               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │           🐍 Python Indexer (fuzzy tag matching)             │
    │   Splits findings → 12 category-raw.md files                │
    └──────────────────────────┬──────────────────────────────────┘
                               ▼
           ┌───────────────────┼───────────────────┐
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │ 🏛️ Wave 1   │     │ 🔧 Wave 2   │     │ 🧠 Phase 3  │
    │ 6 category  │     │ 6 category  │     │ Brain Build │
    │ agents      │ ──▶ │ agents      │ ──▶ │ Profile Gen │
    │ parallel    │     │ parallel    │     │ Memory Inj  │
    └─────────────┘     └─────────────┘     └─────────────┘
```

**What makes it different:**
- ✅ **Every commit analyzed** — zero skipped, merge/empty/binary logged
- ✅ **Artifact mining** — design specs, planning docs, CLAUDE.md, ADRs, PR templates
- ✅ **Chronological hierarchy** — creation order reveals thinking priorities
- ✅ **12 knowledge categories** — including product-thinking and workflow
- ✅ **Crash-proof** — scratchpad files on disk, resume from any interruption
- ✅ **Multi-repo** — cross-repo pattern detection with per-repo attribution
- ✅ **Hybrid memory** — global identity + local details

---

## 🚀 Quick Start

### Install

```bash
claude plugin add github.com/boparaiamrit/build-second-brain
```

### Run

```
/build-second-brain
```

The skill will ask for:

| Prompt | What to enter |
|:---|:---|
| 📂 **Repo path(s)** | One or more git repos (comma or space separated) |
| 🏷️ **Brain name** | Your brain's name (e.g., "Amrit's Brain") |
| 🌍 **Memory scope** | `hybrid` (default), `global`, or `local` |

Then it runs all phases automatically with maximum parallelism.

### 🔀 Memory Scope Options

| | Scope | Where identity lives | Where details live |
|:---:|:---|:---|:---|
| 🌐 | **hybrid** (default) | `~/.claude/CLAUDE.md` (loads everywhere) | Project memory dir (local) |
| 🌍 | **global** | `~/.claude/CLAUDE.md` (loads everywhere) | Project memory dir (local) |
| 📁 | **local** | Project memory dir only | Project memory dir only |

---

## 🏗️ How It Works — The 5-Phase Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  PREFLIGHT  │───▶│   HARVEST   │───▶│    INDEX    │───▶│ CATEGORIZE  │───▶│  SYNTHESIZE │
│  Validate   │    │  5 agents   │    │   Python    │    │ 12 agents   │    │  3 agents   │
│  repos,     │    │  parallel   │    │  indexer    │    │  2 waves    │    │  sequential │
│  paths,     │    │  + artifact │    │  fuzzy      │    │  of 6       │    │  brain +    │
│  Python     │    │    harvest  │    │  matching   │    │             │    │  profile +  │
│             │    │             │    │             │    │             │    │  memory     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### ⛏️ Phase 1 + 1A: HARVEST

**5 parallel agent teammates** analyze every commit chronologically:
- Claims batches of 20 commits (configurable to 50 for large repos)
- Runs `git show <hash>` on each commit for full diff analysis
- Extracts structured findings with per-commit category tagging
- Writes everything to `scratchpad/batch-<repo>-NNN.md` **immediately**

**Phase 1A** mines non-code artifacts in chronological order:
- 📄 Design specs and planning docs
- 📋 CLAUDE.md, AGENTS.md, GEMINI.md
- 📝 PR templates, issue templates, ADRs
- 📊 GSD PROJECT.md, PLAN.md files
- 📖 README files and memory files

### 🔎 What Gets Extracted

#### From Every Commit

| Signal | Example |
|:---|:---|
| 🔀 **What changed and why** | Inferred from diff + message context |
| 🧩 **Patterns detected** | "Moved sync operation to async worker" |
| ⚖️ **Decisions made** | "Chose Redis over DB polling" |
| 🐛 **Problems solved** | "Fixed race condition in queue worker" |
| 🏷️ **Category tags** | For Phase 2 filtering |

#### From Project Artifacts

| Signal | Example |
|:---|:---|
| 💡 **Product thinking** | How features are scoped, trade-offs analyzed, what gets rejected |
| 📐 **Planning philosophy** | How work is broken down and sequenced |
| 🚫 **Non-negotiables** | From CLAUDE.md, project instructions |
| 💬 **Communication style** | From docs, PR templates, READMEs |
| 📅 **Chronological hierarchy** | What was documented first reveals priorities |

### 🐍 Phase 1.5: INDEX

Python indexer splits all scratchpad findings by category tag:
- Fuzzy tag matching (normalizes hyphens/underscores/spaces)
- Untagged commits → `uncategorized` bucket (not all categories)
- Produces 12 `<slug>-raw.md` files + `statistics-raw.md`
- Each Phase 2 agent reads only ~1/12th of total content

### 📊 Phase 2: CATEGORIZE — 12 Agents in 2 Waves

**Wave 1 (6 parallel):** architecture, tech-stack, debugging, scaling, security, product-thinking

**Wave 2 (6 parallel):** data-modeling, code-style, refactoring, integration, error-handling, workflow

Each agent reads its pre-indexed file and organizes findings into patterns, principles, evolution, and key decisions.

### 🧬 Phase 3: SYNTHESIZE — 3 Sequential Agents

| # | Agent | What it does |
|:---:|:---|:---|
| 1 | 🏗️ **Brain Builder** | Creates `second-brain/` directory with all pattern files, playbooks, raw data |
| 2 | 🧬 **Profile Generator** | Creates the holistic engineer profile document |
| 3 | 💾 **Memory Injector** | Writes Claude memory files for future sessions |

---

## 📚 12 Knowledge Categories

Every commit and artifact is tagged with one or more categories. Phase 2 agents specialize in exactly one each.

#### 🔷 Code Categories (6)

| # | Category | Description |
|:---:|:---|:---|
| 1 | 🏛️ **architecture** | System design, module boundaries, layering decisions, dependency management |
| 2 | 🔧 **tech-stack** | Language, framework, and tool choices with rationale |
| 3 | 🗄️ **data-modeling** | Schema design, migrations, relationships, query patterns |
| 4 | 🔗 **integration** | API design, service communication, third-party integrations |
| 5 | 🎨 **code-style** | Naming conventions, formatting preferences, structural patterns |
| 6 | ♻️ **refactoring** | Cleanup patterns, tech debt management, incremental improvement |

#### 🔶 Ops Categories (4)

| # | Category | Description |
|:---:|:---|:---|
| 7 | 🐛 **debugging** | Diagnostic approaches, root cause analysis, investigation patterns |
| 8 | ⚡ **scaling** | Performance optimization, growth handling, resource management |
| 9 | 🔒 **security** | Auth patterns, validation, encryption, access control |
| 10 | 🚨 **error-handling** | Retry logic, fallbacks, circuit breakers, resilience patterns |

#### 🟣 Thinking Categories (2) — ✨ NEW

| # | Category | Description |
|:---:|:---|:---|
| 11 | 💡 **product-thinking** | Feature scoping, requirements analysis, trade-off decisions, what gets built vs rejected |
| 12 | 📋 **workflow** | Planning patterns, communication style, documentation habits, process decisions |

---

## 📦 What You Get

### 🗂️ Structured Knowledge Base

```
second-brain/
├── 📁 profile/
│   └── 🧬 engineer-profile.md            Your complete builder DNA
├── 📁 patterns/
│   ├── 🏛️ architecture-patterns.md       System design patterns
│   ├── ⚡ scaling-patterns.md             How you handle growth
│   ├── 🐛 debugging-patterns.md           How you diagnose bugs
│   ├── 🔒 security-patterns.md            Auth & validation approach
│   ├── 🗄️ data-modeling-patterns.md       Schema & migration patterns
│   ├── 🔗 integration-patterns.md         API & service connections
│   ├── 🚨 error-handling-patterns.md      Retry & resilience
│   └── ♻️ refactoring-patterns.md         Cleanup patterns
├── 📁 philosophy/
│   ├── 💡 product-thinking.md             Feature scoping & trade-offs
│   └── 📋 workflow.md                     Planning & process patterns
├── 📁 decisions/
│   └── ⚖️ tech-decisions.md               Every tech choice with reasoning
├── 📁 conventions/
│   └── 🎨 code-style.md                   Naming & structure conventions
├── 📁 evolution/
│   └── 📈 architecture-evolution.md       How the system evolved over time
├── 📁 playbooks/
│   ├── 🐛 debugging-playbook.md           Step-by-step debugging guide
│   └── ⚡ scaling-playbook.md              Step-by-step scaling guide
└── 📁 raw/
    ├── 📝 commit-log.md                   Annotated commit history
    └── 📊 statistics.md                   Numbers breakdown
```

### 🧬 Holistic Builder Profile

A single document that captures your complete engineering DNA — not just how you code, but how you **think**:

| | Dimension | What it captures |
|:---:|:---|:---|
| 🧠 | **Core Philosophy** | Your fundamental beliefs about building products, systems, and code |
| 🔧 | **Tech Stack DNA** | Your go-to technology choices and why you pick them |
| 🏛️ | **Architecture Fingerprint** | How you structure systems and make design trade-offs |
| 🐛 | **Debugging Style** | Your step-by-step diagnostic process |
| ⚖️ | **Decision Patterns** | When faced with X, you choose Y because Z |
| 🚫 | **Non-Negotiables** | Things you ALWAYS or NEVER do |
| 💡 | **Product Thinking** | How you scope features, analyze trade-offs, say no |
| 📋 | **Workflow & Process** | How you plan, communicate, break down work |
| 📈 | **Evolution** | How your thinking changed over time |

### 💾 Claude Memory Injection

Three memory files injected into your Claude Code memory directory:

| | File | Type | What it does |
|:---:|:---|:---:|:---|
| 🧬 | `second-brain-profile.md` | `user` | Core identity — philosophy, stack, architecture, debugging style |
| 📐 | `second-brain-patterns.md` | `feedback` | Patterns to follow — architecture, product thinking, workflow, scaling |
| ⚖️ | `second-brain-decisions.md` | `feedback` | Decision rules — tech defaults, non-negotiables, when-X-choose-Y |

> 🌐 **Hybrid mode** also appends a concise brain summary to `~/.claude/CLAUDE.md` — loaded in **every** Claude session globally. Your identity follows you across all projects.

**Result:** Every future Claude session already knows how you think. 🎯

---

## 🪝 6 Runtime Enforcement Hooks

Event-driven enforcement that keeps the build honest — validates paths, checks output structure, and prevents premature completion.

| | Hook | Event | What it does |
|:---:|:---|:---|:---|
| 📂 | **Path Validator** | `PreToolUse` · Write/Edit | Ensures files go to correct absolute paths, validates batch and artifact filename conventions |
| ⚠️ | **Relative Path Warner** | `PreToolUse` · Bash | Warns if bash commands use relative paths instead of absolute |
| ✅ | **Scratchpad Validator** | `PostToolUse` · Write | Verifies scratchpad files contain proper `## Commit:` or `## Artifact:` headers |
| 📊 | **Completion Checker** | `SubagentStop` | Counts batch files, artifact files, category files — reports build progress |
| 🛑 | **Stop Guard** | `Stop` | Blocks completion if profile is missing or progress.md has unchecked items |
| 🔄 | **Compact Reminder** | `PreCompact` | Reminds orchestrator to re-read config.md and progress.md after context compression |

---

## 🔀 Multi-Repo Support

Analyze multiple repos together to detect cross-repo patterns:

```bash
# Separate frontend and backend repos
/build-second-brain
> Repo paths: ~/projects/my-backend, ~/projects/my-frontend
```

Each repo gets its own:
- 📄 Commit file (`my-backend-commits.txt`)
- 📁 Batch numbering (`batch-my-backend-001-commits-1-20.md`)
- 🗂️ Artifact harvest (`artifacts-my-backend.md`)

All findings merge during indexing — category agents see the full picture across repos. Cross-repo patterns (e.g., "always updates frontend types when backend API changes") are detected automatically.

---

## 🔄 Crash Recovery & Resume

Everything persists to disk — **nothing is kept only in memory**:

| File | What it stores |
|:---|:---|
| 📋 `config.md` | Brain name, repo paths, scope, batch size, HEAD hashes, Python command |
| ✅ `progress.md` | Checkboxes for every item in every phase |
| 📁 `scratchpad/` | One file per batch + artifact harvest, written after every commit |

On resume, the orchestrator parses `progress.md` to find the first unchecked item and continues from there. Harvest agents check existing scratchpad files for already-analyzed commits and skip them.

---

## ✨ Features

| | Feature | Details |
|:---:|:---|:---|
| ✅ | **Every commit analyzed** | Zero skipped — merge/empty/binary commits logged appropriately |
| 🔀 | **Multi-repo support** | Cross-repo pattern detection across related repos |
| 📄 | **Artifact mining** | Design specs, planning docs, CLAUDE.md, ADRs, PR templates |
| ⚡ | **Maximum parallelism** | 5 teammate agents + 12 parallel category agents (2 waves of 6) |
| 💪 | **Crash-proof** | Scratchpad persistence on disk — resume from any interruption |
| 📏 | **Large diff handling** | >500 line diffs fall back to `git show --stat` + selective inspection |
| 📊 | **Progress tracking** | Real-time cron-based progress monitoring with checkboxes |
| 🌐 | **Hybrid memory** | Global identity in `~/.claude/CLAUDE.md` + local detailed files |
| 🐍 | **Python fallback** | Detects `python3`/`python` with bash fallback if unavailable |
| ⚙️ | **Configurable batch size** | 20 default, auto-suggests 50 for repos with >5000 commits |
| 🔒 | **Data isolation** | All agent prompts treat commit content as untrusted data |
| 🔍 | **Post-run verification** | `verify.py` runs 12+ automated checks on the final output |

---

## 📊 Token Estimates

| Repo Size | ⛏️ Harvest | 📊 Categorize | 🧬 Synthesize | 💰 Total |
|:---|:---|:---|:---|:---|
| **100 commits** | ~200K-500K | ~50K | ~50K | **~300K-600K** |
| **500 commits** | ~1M-2.5M | ~250K | ~100K | **~1.5M-3M** |
| **1,000 commits** | ~2M-5M | ~500K | ~200K | **~3M-6M** |
| **5,000 commits** | ~10M-25M | ~2M | ~500K | **~13M-28M** |

---

## ⚙️ Requirements

| | Requirement | Notes |
|:---:|:---|:---|
| 🤖 | **Claude Code** | With Agent Teams support (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Falls back to wave-based subagents if unavailable. |
| 📂 | **Git** | Local access to the repository. Private repos work — no GitHub API needed. |
| 🐍 | **Python 3.7+** | For the indexer script. Bash fallback available but less accurate. |

---

## 🗂️ Plugin Structure

```
second-brain/
├── 📁 .claude-plugin/
│   └── plugin.json                            Plugin manifest
├── 📁 skills/build-second-brain/
│   ├── SKILL.md                               Main orchestrator (600+ lines)
│   ├── 📁 references/
│   │   ├── harvest-agent-prompt.md            Phase 1: commit analysis agent
│   │   ├── artifact-harvest-prompt.md         Phase 1A: artifact mining agent
│   │   ├── category-agent-prompt.md           Phase 2: category specialist agent
│   │   ├── brain-builder-prompt.md            Phase 3: knowledge base builder
│   │   ├── profile-generator-prompt.md        Phase 3: engineer profile writer
│   │   ├── memory-injector-prompt.md          Phase 3: Claude memory injector
│   │   └── progress-template.md               Progress tracking template
│   └── 📁 scripts/
│       ├── indexer.py                         Category indexer (fuzzy matching)
│       └── verify.py                          Post-run verification (12+ checks)
├── 📁 hooks/
│   ├── hooks.json                             6 runtime enforcement hooks
│   └── 📁 scripts/
│       ├── validate-write-paths.sh            Path & filename validation
│       ├── validate-scratchpad-output.sh      Output structure validation
│       └── validate-agent-completion.sh       Completion progress check
├── 🌐 index.html                              Documentation website
├── 📖 README.md
└── 📄 LICENSE                                 MIT
```

---

## 💭 Why "Second Brain"?

Your git history is a time machine of your thinking:

- 🔀 **Every commit** answers: *Why did you change this architecture?*
- 📐 **Every design spec** answers: *What trade-offs did you weigh?*
- 📋 **Every planning doc** answers: *How do you break down problems?*
- 🚫 **Every CLAUDE.md** answers: *What do you insist on?*
- 🧠 **Every ADR** answers: *What alternatives did you consider and reject?*

Most engineers have **thousands** of these decisions buried in their repos. This plugin extracts them, organizes them into 12 categories, generates a holistic builder profile, and injects it into Claude's memory — so it stops being a generic tool and starts being ***your*** tool.

---

## 🤝 Contributing

Contributions welcome! Feel free to open issues or PRs.

**Areas for contribution:**
- 🏷️ New knowledge categories
- 🐍 Alternative indexer implementations
- 📄 Additional artifact types to mine
- 🧬 Improved profile generation templates
- 🔀 Support for non-git VCS
- 🌍 Additional memory scope strategies

---

## 📄 License

[MIT](LICENSE)

---

## 👤 Author

**Amritpal Singh** — [@boparaiamrit](https://github.com/boparaiamrit)

Built with [Claude Code](https://claude.ai/claude-code) ⚡

---

<p align="center">
  <sub>Made with intensity in Canada 🇨🇦</sub>
</p>
