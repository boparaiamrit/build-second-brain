# Progress Template

Use this template when creating the initial `progress.md` file.

```markdown
# Second Brain Build Progress
Brain Name: {{BRAIN_NAME}}
Repo: {{REPO_PATH}}
Total Commits: {{TOTAL_COMMITS}}
Batch Size: {{BATCH_SIZE}}
Total Batches: {{TOTAL_BATCHES}}
Started: {{TIMESTAMP}}

## Phase 1: Harvest
{{#for each batch}}
- [ ] batch-{{NNN}} (commits {{start}}-{{end}})
{{/for}}

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
