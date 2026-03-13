# Progress Template

The orchestrating agent generates `progress.md` with one checkbox per item.

## Single-Repo Example (60 commits, batch size 20)

```markdown
# Second Brain Build Progress
Brain Name: Amrit's Brain
Repos: myapp (/home/amrit/projects/myapp)
Memory Scope: hybrid
Total Commits: 60
Batch Size: 20
Total Batches: 3
Started: 2026-03-13T10:00:00

## Phase 1: Harvest
### myapp (60 commits, 3 batches)
- [ ] batch-myapp-001 (commits 1-20)
- [ ] batch-myapp-002 (commits 21-40)
- [ ] batch-myapp-003 (commits 41-60)

## Phase 1.5: Index
- [ ] Pre-categorization indexing

## Phase 2: Categorize
- [ ] architecture
- [ ] tech-stack
- [ ] debugging
- [ ] scaling
- [ ] security
- [ ] data-modeling
- [ ] code-style
- [ ] refactoring
- [ ] integration
- [ ] error-handling

## Phase 3: Synthesize
- [ ] brain-builder
- [ ] profile-generator
- [ ] memory-injector

## Completion
- [ ] Verification
- [ ] Report
```

## Multi-Repo Example (backend: 500 commits, frontend: 300 commits, batch size 20)

```markdown
# Second Brain Build Progress
Brain Name: Amrit's Brain
Repos: my-backend (/home/amrit/projects/my-backend), my-frontend (/home/amrit/projects/my-frontend)
Memory Scope: hybrid
Total Commits: 800
Batch Size: 20
Total Batches: 40
Started: 2026-03-13T10:00:00

## Phase 1: Harvest
### my-backend (500 commits, 25 batches)
- [ ] batch-my-backend-001 (commits 1-20)
- [ ] batch-my-backend-002 (commits 21-40)
...
- [ ] batch-my-backend-025 (commits 481-500)

### my-frontend (300 commits, 15 batches)
- [ ] batch-my-frontend-001 (commits 1-20)
- [ ] batch-my-frontend-002 (commits 21-40)
...
- [ ] batch-my-frontend-015 (commits 281-300)

## Phase 1.5: Index
- [ ] Pre-categorization indexing

## Phase 2: Categorize
- [ ] architecture
- [ ] tech-stack
- [ ] debugging
- [ ] scaling
- [ ] security
- [ ] data-modeling
- [ ] code-style
- [ ] refactoring
- [ ] integration
- [ ] error-handling

## Phase 3: Synthesize
- [ ] brain-builder
- [ ] profile-generator
- [ ] memory-injector

## Completion
- [ ] Verification
- [ ] Report
```

## Rules

Generate one `- [ ] batch-<REPO_ID>-NNN (commits start-end)` line per batch where:
- REPO_ID = the repo's short identifier (directory name)
- NNN = zero-padded 3-digit batch number (per repo, starting at 001)
- start = (batch-1) * batch_size + 1
- end = min(batch * batch_size, total_commits_for_this_repo)

Group Phase 1 batches by repo with `### <repo-id>` subheadings.

Mark items `[x]` as they complete. On resume, parse checkmarks to find first unchecked item.
