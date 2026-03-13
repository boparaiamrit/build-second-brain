# Progress Template

The orchestrating agent generates `progress.md` with one checkbox per item. Example for a 60-commit repo with batch size 20:

```markdown
# Second Brain Build Progress
Brain Name: Amrit's Brain
Repo: /home/amrit/projects/myapp
Total Commits: 60
Batch Size: 20
Total Batches: 3
Started: 2026-03-13T10:00:00

## Phase 1: Harvest
- [ ] batch-001 (commits 1-20)
- [ ] batch-002 (commits 21-40)
- [ ] batch-003 (commits 41-60)

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

Generate one `- [ ] batch-NNN (commits start-end)` line per batch where:
- NNN = zero-padded 3-digit batch number
- start = (batch-1) * batch_size + 1
- end = min(batch * batch_size, total_commits)

Mark items `[x]` as they complete. On resume, parse checkmarks to find first unchecked item.
