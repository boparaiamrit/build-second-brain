# Pull Request Template

> Place this file at `.github/PULL_REQUEST_TEMPLATE.md` in your repository.
> Every PR will auto-populate with this template.

---

```markdown
## What This PR Does

<!-- One-paragraph summary. What changed and why? Link to the feature spec or design doc if available. -->



## Why

<!-- Link to issue, ticket, or conversation that prompted this change. -->

Closes #<!-- issue number -->

<!-- If no ticket exists, explain the motivation: -->
<!-- - What problem does this solve? -->
<!-- - What happens if we don't make this change? -->

---

## Customer Types Affected

<!-- Check ALL that apply. Every PR must consider all three customer types. -->

- [ ] **UC1** — Single company, single workspace, single domain
- [ ] **UC2** — Single workspace, multiple domains (Person de-duplication relevant)
- [ ] **UC3** — Multiple workspaces / full MSSP (workspace isolation, Company Library, Blueprints)
- [ ] **None** — Infrastructure/tooling only (no customer-facing impact)

### UC Impact Notes

<!-- For each checked UC, briefly describe the impact: -->
<!-- UC1: "Works without any multi-tenant UI. No extra clicks." -->
<!-- UC2: "Domain tabs show breakdown. Person de-dup applied." -->
<!-- UC3: "Blueprint deployment supported. Workspace isolation verified." -->



---

## Planning

<!-- Complex features require a planning document BEFORE implementation. -->

- [ ] Planning document exists (link below)
- [ ] Planning document reviewed and approved
- [ ] N/A — This is a small change that does not require a planning doc

**Planning doc link:** <!-- paste URL or file path -->

---

## Change Type

<!-- Check ONE primary type. -->

- [ ] New feature
- [ ] Enhancement to existing feature
- [ ] Bug fix
- [ ] Refactoring (no behavior change)
- [ ] Performance improvement
- [ ] Security fix
- [ ] Documentation
- [ ] Infrastructure / CI / CD
- [ ] Database migration
- [ ] Dependency update

---

## Schema Changes

<!-- Database migrations are high-risk. Document them thoroughly. -->

- [ ] **Yes** — This PR includes schema/migration changes
- [ ] **No** — No schema changes

### If Yes:

**Tables added/modified:**
<!-- List each table and what changed -->
<!-- - `my_new_table`: new table with companyId, workspaceId, domainId -->
<!-- - `recipients`: added `newColumn` (nullable, no backfill needed) -->



**Migration details:**
- [ ] Migration is reversible (DOWN migration exists and tested)
- [ ] Existing data handled (backfill for NOT NULL columns, default values)
- [ ] New tables have `companyId`, `workspaceId`, `domainId`
- [ ] `domainId` indexed (`idx_{table}_domain`)
- [ ] Soft delete column present (`deletedAt`)
- [ ] Cascade rules explicit on foreign keys
- [ ] Uniqueness constraints scoped per domain (not globally unique)

**Estimated migration time on production data:**
<!-- "< 1 second", "~30 seconds", "~5 minutes (needs maintenance window)" -->



---

## Breaking Changes

- [ ] **Yes** — This PR includes breaking changes
- [ ] **No** — Fully backward compatible

### If Yes:

**What breaks:**
<!-- - API response shape changed for /api/recipients -->
<!-- - Removed deprecated `legacyField` from DTO -->



**Deprecation plan:**
<!-- How will existing consumers migrate? Timeline? -->
<!-- - v2 endpoint added alongside v1 -->
<!-- - v1 deprecated, will be removed in 2 weeks -->
<!-- - Frontend already updated to use v2 -->



**Affected consumers:**
<!-- List services, frontends, or integrations that depend on the changed contract -->



---

## Testing

### Automated Tests

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] E2E tests added/updated
- [ ] Multi-tenant isolation tests added (workspace A cannot see workspace B data)
- [ ] N/A — This change does not require new tests (explain why below)

**Test coverage notes:**
<!-- What is tested? What edge cases are covered? -->
<!-- - Happy path: create recipient with valid data -->
<!-- - Error: duplicate email within same domain -->
<!-- - Error: exceed subscription recipient limit -->
<!-- - Isolation: workspace A query returns 0 results for workspace B data -->



### Manual Testing

- [ ] Tested locally with UC1 setup (single workspace, single domain)
- [ ] Tested locally with UC2 setup (single workspace, multiple domains)
- [ ] Tested locally with UC3 setup (multiple workspaces)
- [ ] N/A — Automated tests are sufficient

**Manual test steps:**
<!-- 1. Log in as workspace admin -->
<!-- 2. Navigate to Recipients > Import -->
<!-- 3. Upload CSV with 50 rows -->
<!-- 4. Verify preview shows correct data -->
<!-- 5. Confirm import, verify all rows created -->



---

## Screenshots / Recordings

<!-- Required for all frontend changes. Optional for backend-only changes. -->

| Before | After |
|--------|-------|
| <!-- screenshot or "N/A" --> | <!-- screenshot --> |

<!-- For complex UI flows, attach a screen recording (Loom, GIF, or MP4) -->
**Recording:** <!-- paste link or "N/A" -->

---

## Self-Review Checklist

<!-- Check every item BEFORE requesting review. Unchecked items will be flagged by reviewers. -->

### Tenant Isolation (Required)

- [ ] Every new query includes `workspaceId` or `domainId` filter
- [ ] `tenantContext` resolved and checked in service layer
- [ ] No cross-workspace data exposure possible
- [ ] Cache keys scoped by tenant identifiers (`domainId`, `workspaceId`)

### Security (Required)

- [ ] Input validation on every new endpoint (DTO with Zod or class-validator)
- [ ] No SQL injection vectors (parameterized queries only)
- [ ] No `@Public()` on protected endpoints
- [ ] No secrets in source code (API keys, tokens, passwords)
- [ ] No XSS vectors in user-generated content

### Code Quality (Required)

- [ ] No `any` types in TypeScript
- [ ] No N+1 queries (JOIN or `inArray`, never loop)
- [ ] No unbounded queries (LIMIT on every SELECT)
- [ ] No `console.log` in production code (use NestJS Logger)

### Observability (Required for mutations)

- [ ] `@Audit` decorator on POST/PATCH/DELETE endpoints
- [ ] BullMQ processors extend `BaseProcessor` (if applicable)
- [ ] Error messages do not leak internal state (stack traces, SQL, paths)

### Frontend (Required for UI changes)

- [ ] Loading state (skeleton or spinner)
- [ ] Empty state (no data message with call-to-action)
- [ ] Error state (API failure with retry option)
- [ ] Toast on mutation success/failure (sonner)
- [ ] Forms validated with Zod schema
- [ ] Progressive complexity: UC1 sees simple UI, UC3 sees full MSSP

### Performance (Required for data-heavy features)

- [ ] >1000 items -> BullMQ (not in-request processing)
- [ ] Pagination on list endpoints
- [ ] Database indexes match new query patterns
- [ ] Redis caching for read-heavy paths with TTL

---

## Reviewer Notes

<!-- Anything specific you want reviewers to focus on? Known concerns? -->
<!-- - "The de-duplication logic in `service.ts:42-78` is complex — please review carefully" -->
<!-- - "Not sure if the cache invalidation covers all edge cases" -->
<!-- - "Migration is tricky — tested on a copy of production data" -->



---

## Deploy Notes

<!-- Anything needed for deployment beyond the standard pipeline? -->

- [ ] No special deploy steps needed
- [ ] Environment variables added (listed below)
- [ ] Feature flag required (flag name below)
- [ ] Database migration needs downtime window
- [ ] Third-party service configuration needed
- [ ] Cache flush required after deploy

### If special steps needed:

**New environment variables:**
<!-- | Variable | Description | Example Value | Required? | -->
<!-- |----------|-------------|---------------|----------| -->



**Feature flag:**
<!-- Flag name, default state, rollout plan -->



**Deploy order:**
<!-- If multiple services need coordinated deployment -->
<!-- 1. Run migration -->
<!-- 2. Deploy backend -->
<!-- 3. Deploy frontend -->
<!-- 4. Enable feature flag -->



---

## Post-Deploy Verification

<!-- How will you verify the deployment is successful? -->

- [ ] Smoke test: <!-- describe the key user flow to verify -->
- [ ] Monitoring: <!-- what metrics/alerts to watch -->
- [ ] Rollback plan: <!-- how to revert if something goes wrong -->
```
