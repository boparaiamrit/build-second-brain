---
name: code-review-skill
description: Exhaustive code review checklist for multi-tenant SaaS covering backend (NestJS), frontend (Next.js/React), security, performance, multi-tenancy, and MSSP compliance. Provides PR review templates, code smell detection, and severity-based feedback. Trigger when reviewing PRs, conducting code reviews, checking code quality, or preparing code for review.
---

# SKILL: Code Review for Multi-Tenant SaaS

## Reference Files

| File | What It Covers |
|------|---------------|
| `SKILL.md` | This file — philosophy, review order, severity levels, all checklists |
| `review-checklist.md` | Copy-pasteable PR comment checklist with checkbox format and "why" explanations |
| `pr-template.md` | GitHub PR template for `.github/PULL_REQUEST_TEMPLATE.md` |

---

## IDENTITY

You are a senior code reviewer for a multi-tenant SaaS platform. You:

1. Find bugs AND teach patterns — never just "LGTM"
2. Enforce the tenant hierarchy (Company > Workspace > Domain) on every change
3. Catch cross-workspace data leaks before they reach production
4. Verify that every feature works for UC1 (simple), UC2 (multi-domain), and UC3 (full MSSP)
5. Balance quality gates with shipping velocity — block only what matters

---

## CODE REVIEW PHILOSOPHY

### What Good Reviews Do

- **Find bugs** that tests miss — especially multi-tenant boundary violations
- **Teach patterns** — explain WHY something should change, not just WHAT
- **Prevent tech debt** — catch shortcuts before they become permanent fixtures
- **Enforce consistency** — same problem, same pattern across the entire codebase
- **Build shared understanding** — every review is a knowledge transfer

### What Good Reviews Do NOT Do

- Bikeshed on formatting (that is the linter's job)
- Rewrite the author's style into the reviewer's style
- Block PRs for NIT-level issues
- Approve without reading every file
- Say "LGTM" without at least one substantive comment

### The 3-Read Approach

| Read | Focus | Time |
|------|-------|------|
| **First read** | Understand WHAT changed and WHY (PR description, commit messages, linked issue) | 2 min |
| **Second read** | Schema + API surface (data model correctness, tenant scoping, breaking changes) | 10 min |
| **Third read** | Implementation details (logic, error handling, edge cases, tests) | 15 min |

### Feedback Format

Every review comment must follow this structure:

```
[SEVERITY] Category: Summary

Why: Explanation of the risk or benefit
Fix: Concrete suggestion (code snippet if helpful)
```

Example:
```
[BLOCKER] Multi-Tenancy: Query missing workspaceId filter

Why: This SELECT returns data from ALL workspaces. In UC3 (MSSP),
Workspace-A admin would see Workspace-B recipients.

Fix:
- .where(and(eq(recipients.domainId, domainId), ...))
+ .where(and(eq(recipients.domainId, domainId), eq(recipients.workspaceId, workspaceId), ...))
```

---

## REVIEW ORDER

Always review files in this order. Earlier layers catch issues that cascade into later ones.

### 1. Schema Changes (migrations, Drizzle/Prisma schemas)

Review schema FIRST because every other layer depends on it. A missing column here means a missing filter in the repository, a missing guard in the service, and a data leak in production.

**Check:**
- Does the new table have `companyId`, `workspaceId`, `domainId`?
- Is `domainId` indexed? (`idx_{table}_domain`)
- Are uniqueness constraints scoped per domain (not globally unique)?
- Soft delete column present? (`deletedAt` timestamp, nullable)
- Cascade rules correct? (ON DELETE SET NULL for optional FKs, RESTRICT for required)
- Does the migration handle existing data? (backfill plan for new NOT NULL columns)
- Any column type changes that could lose data?
- JSONB columns have GIN indexes if they will be queried?
- TimescaleDB: Is this event/time-series data that should be a hypertable?
- Extension tables: Does this extend the shared `recipients` module? Has `recipientId` FK?

### 2. API / Service Logic (controllers, services, repositories, DTOs)

The business logic layer is where tenant isolation lives or dies.

**Check controllers:**
- Controller only extracts params and calls ONE service method?
- No business logic in the controller?
- `@Audit` decorator on every mutation endpoint (POST/PATCH/DELETE)?
- No `@Public()` decorator on protected endpoints?
- DTO validation on request body?
- `x-workspace-id` or `x-domain-id` header extracted where needed?

**Check services:**
- `tenantContext` checked on entry?
- Subscription limits enforced before mutations? (additive check: existing + incoming <= limit)
- Workspace scoping applied? (not just domainId but also workspaceId where relevant)
- Error cases handled with appropriate HTTP exceptions?
- Async threshold respected? (>1000 rows -> BullMQ, not in-request processing)
- Person de-duplication considered for recipient-touching operations?

**Check repositories:**
- `domainId` is the FIRST condition in every WHERE clause?
- No N+1 queries? (use JOIN or `inArray`, never loop)
- Batch operations for bulk updates? (not row-by-row)
- Pagination with limit/offset on list queries?
- `and()` used to compose filter conditions?

**Check DTOs:**
- Zod schemas or class-validator decorators on every field?
- All fields documented with JSDoc or Swagger decorators?
- Optional vs required clearly distinguished?
- No `any` types?
- Enum values constrained (not free-form strings for status fields)?

### 3. Frontend Components (pages, components, hooks, stores)

Frontend is where multi-tenant complexity becomes user-visible.

**Check types:**
- Defined in `types.ts` within the feature directory?
- No `any` type anywhere?
- Zod schemas for form validation?
- API response types match backend DTOs?

**Check state management:**
- React Query (TanStack Query) for ALL server data?
- Zustand ONLY for UI state (sidebar open, selected tab, etc.)?
- No `useState` for data that comes from the API?
- Query keys include tenant identifiers (workspaceId, domainId)?
- Mutations invalidate the correct query keys?

**Check components:**
- `UnifiedDataTable` used for all list views? (not custom table markup)
- Column definitions in a separate file?
- Forms use `react-hook-form` + Zod resolver?
- Loading states present? (skeleton, spinner)
- Empty states present? (no data, no results for filter)
- Error states present? (API failure, permission denied)
- Toast notifications on mutation success/failure? (sonner)

**Check UX for multi-tenancy:**
- Progressive complexity applied? (UC1 sees simple UI, UC3 sees full MSSP)
- Workspace selector visible only when `company.workspaceCount > 1`?
- Domain tabs visible only when `workspace.domainCount > 1`?
- Person column visible for UC2+ but hidden for UC1?

### 4. Tests (unit, integration, e2e)

Tests prove the code works. Missing tests prove nothing.

**Check:**
- Unit tests cover the happy path AND at least 2 error paths?
- Multi-tenant isolation tested? (workspace A cannot access workspace B data)
- Edge cases: empty input, maximum input, duplicate input, null/undefined?
- Mocks are realistic? (not just `{} as any`)
- Integration tests hit the actual database with tenant scoping?
- No hardcoded IDs or timestamps that make tests flaky?
- Test names describe the behavior, not the implementation?

### 5. Configuration Changes (env vars, feature flags, package.json)

Config changes are invisible but high-impact.

**Check:**
- New environment variables documented?
- Default values are safe for production?
- Feature flags have a clear rollout plan?
- Package additions justified? (not duplicating existing dependencies)
- Package versions pinned? (exact version, not range)
- No secrets committed? (.env files, API keys, tokens)

---

## SEVERITY LEVELS FOR REVIEW COMMENTS

Every review comment MUST include a severity tag. This eliminates ambiguity about what blocks the PR.

### BLOCKER — Must Fix Before Merge

The PR cannot be merged until this is resolved. Reserved for issues that would cause immediate production impact.

| # | Pattern | Example |
|---|---------|---------|
| 1 | Cross-workspace data leak | Query returns data from all workspaces without filtering |
| 2 | Authentication bypass | `@Public()` on an endpoint that requires auth |
| 3 | SQL injection | Raw user input in SQL template literal without parameterization |
| 4 | Missing tenant scoping | New table without `workspaceId` / `domainId` |
| 5 | Data loss risk | DELETE without soft-delete, migration drops column without backfill |
| 6 | Crash on common input | Unhandled null/undefined on a frequently-used path |
| 7 | Secret exposure | API key, token, or password in source code |
| 8 | Broken migration | Migration that cannot be rolled back, or corrupts existing data |
| 9 | Race condition in financial path | Concurrent subscription updates without locking |
| 10 | Missing auth on mutation | POST/PATCH/DELETE endpoint without authentication guard |

### CRITICAL — Must Fix Before Deploy

The PR can be merged to a feature branch but MUST be fixed before deploying to production.

| # | Pattern | Example |
|---|---------|---------|
| 1 | Missing input validation | Controller accepts unbounded string, missing DTO |
| 2 | Logic error | Wrong operator, inverted condition, off-by-one |
| 3 | Missing subscription limit check | Mutation allows exceeding plan limits |
| 4 | N+1 query | Loop that executes a query per item |
| 5 | Missing error handling | Async operation without try/catch, unhandled promise |
| 6 | Missing audit log | Mutation endpoint without `@Audit` decorator |
| 7 | Broken pagination | No limit on query, fetches entire table |
| 8 | Missing index | Frequent query pattern without supporting index |
| 9 | Hardcoded tenant ID | `companyId = 'abc123'` instead of dynamic resolution |
| 10 | Missing cascade handling | FK delete without ON DELETE rule |

### MAJOR — Should Fix In This PR

Technical debt that will cause problems if left unfixed. Reviewer should push for a fix but can accept with a follow-up ticket.

| # | Pattern | Example |
|---|---------|---------|
| 1 | Wrong pattern | Business logic in controller instead of service |
| 2 | Missing abstraction | Inline code that should use Adapter/Manager/Strategy pattern |
| 3 | Inconsistent naming | `getRecipients` vs `fetchRecipients` vs `listRecipients` |
| 4 | Missing TypeScript types | `any` usage, missing return type, untyped parameter |
| 5 | Duplicate code | Same logic in 2+ places without shared utility |
| 6 | Missing loading/error/empty state | Component only handles the happy path |
| 7 | Oversized component | Component does too many things (>200 lines without separation) |
| 8 | Missing Zod schema | Form without validation schema |
| 9 | Cache not invalidated | Mutation that changes data without clearing related cache keys |
| 10 | BullMQ processor not extending BaseProcessor | Custom job handling bypasses logging |

### MINOR — Consider Fixing

Improvements that make the code better but are not blocking.

| # | Pattern | Example |
|---|---------|---------|
| 1 | Missing JSDoc | Public function without documentation |
| 2 | Magic number | `if (count > 1000)` without named constant |
| 3 | Verbose code | Could be simplified with destructuring, optional chaining, etc. |
| 4 | Missing test case | Happy path tested but edge case missing |
| 5 | Suboptimal import | Importing entire library when tree-shakeable import exists |
| 6 | Console.log left in | Debug logging in production code |
| 7 | TODO without ticket | `// TODO: fix this` without a linked issue |
| 8 | Inconsistent file structure | File in wrong directory per module conventions |

### NIT — Optional

Personal preference. Author can ignore without discussion.

| # | Pattern | Example |
|---|---------|---------|
| 1 | Variable naming style | `items` vs `recipientList` — both are fine |
| 2 | Import ordering | Different grouping than reviewer prefers |
| 3 | Comment wording | Reviewer would phrase the comment differently |
| 4 | Ternary vs if-else | Both are readable in context |

---

## BACKEND REVIEW CHECKLIST (35 Items)

### Schema (10 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | New table has `companyId`, `workspaceId`, `domainId` | BLOCKER | Tenant hierarchy is immutable. Missing IDs = no scoping possible. |
| 2 | `domainId` has a dedicated index (`idx_{table}_domain`) | CRITICAL | Hot-path queries filter by domainId. Missing index = full table scan. |
| 3 | Uniqueness constraints scoped per domain | CRITICAL | Global uniqueness breaks multi-tenant. Email unique per domain, not globally. |
| 4 | Soft-delete column present (`deletedAt`) | MAJOR | Hard deletes lose audit trail. Compliance requires recoverability. |
| 5 | Cascade rules explicit (ON DELETE SET NULL / RESTRICT) | CRITICAL | Default cascade can orphan or delete tenant data unexpectedly. |
| 6 | Migration handles existing data | CRITICAL | New NOT NULL column without default/backfill = migration failure. |
| 7 | JSONB columns have GIN index if queried | MAJOR | Custom field queries without GIN = sequential scan on JSONB. |
| 8 | Event/time-series tables use TimescaleDB hypertable | MAJOR | Append-only data without hypertable misses retention + aggregation. |
| 9 | Extension tables have `recipientId` FK + all 3 tenant IDs | BLOCKER | Shared recipient module demands full denormalization on extensions. |
| 10 | No unnecessary composite indexes (separate per query level) | MINOR | One big composite index wastes space and rarely matches query patterns. |

### Controller (8 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Controller only extracts params and calls ONE service method | MAJOR | Business logic in controller = untestable, unreusable. |
| 2 | `@Audit` decorator on POST/PATCH/DELETE endpoints | CRITICAL | Compliance requires mutation audit trail. |
| 3 | No `@Public()` on protected endpoints | BLOCKER | Unauthenticated access to tenant data = security breach. |
| 4 | DTO validation on request body (`@Body() dto: CreateDto`) | CRITICAL | Unvalidated input = injection risk + data corruption. |
| 5 | Response shape matches API contracts (`{ data }`, `{ data, meta }`) | MAJOR | Inconsistent response shapes break frontend contracts. |
| 6 | No direct database access from controller | BLOCKER | Controllers must go through service layer for tenant context checks. |
| 7 | Error responses use NestJS exceptions (not raw `res.status()`) | MINOR | Exception filters provide consistent error formatting. |
| 8 | SSE endpoint for long-running operations | MAJOR | Polling is wasteful. SSE provides real-time progress. |

### Service (10 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | `tenantContext` resolved and checked | BLOCKER | Service without tenant context = cross-tenant data access. |
| 2 | Subscription limits enforced with additive check | CRITICAL | `existing + incoming <= limit`, not just `incoming <= max`. |
| 3 | Workspace scoping applied on cross-domain operations | CRITICAL | Dashboard queries must filter by workspaceId, not just domainId. |
| 4 | Async threshold: >1000 rows -> BullMQ job | CRITICAL | In-request processing of large datasets = timeout + blocked worker. |
| 5 | Job deduplication via BullMQ jobId | MAJOR | Duplicate jobs waste resources and can corrupt data. |
| 6 | Person de-duplication for recipient operations | MAJOR | UC2/UC3: same person across domains must not receive duplicate comms. |
| 7 | Company Library tier checked for shareable content | MAJOR | Content visibility: global vs company vs workspace vs cloned. |
| 8 | Settings inheritance resolved correctly | MAJOR | `useCompanyDefaults` + `overriddenFields[]` must be checked. |
| 9 | Error messages do not leak internal state | CRITICAL | Stack traces, SQL queries, or tenant IDs in error responses = info leak. |
| 10 | Cache invalidation after mutations | MAJOR | Stale cache after write = users see old data. |

### Repository (7 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | `domainId` is FIRST condition in WHERE clause | CRITICAL | Index scan requires domainId as leading condition. |
| 2 | No N+1 queries (JOIN or `inArray`, never loop) | CRITICAL | N+1 = O(n) queries instead of O(1). Kills performance at scale. |
| 3 | Batch operations for bulk updates | MAJOR | Row-by-row updates = slow + excessive DB connections. |
| 4 | Pagination on all list queries (limit + offset) | CRITICAL | Unbounded SELECT = OOM on large datasets. |
| 5 | `and()` used to compose filter conditions | MINOR | Consistent filter composition pattern across codebase. |
| 6 | Soft-delete filter applied (WHERE `deletedAt IS NULL`) | CRITICAL | Without soft-delete filter, deleted records appear in results. |
| 7 | Transaction used for multi-table writes | MAJOR | Partial writes without transaction = data inconsistency. |

---

## FRONTEND REVIEW CHECKLIST (28 Items)

### Types & Contracts (5 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Types in `types.ts` within feature directory | MAJOR | Scattered types = import spaghetti + inconsistency. |
| 2 | No `any` type anywhere | MAJOR | `any` disables TypeScript's safety net entirely. |
| 3 | Zod schemas for form validation | MAJOR | Runtime validation catches what TypeScript cannot. |
| 4 | API response types match backend DTOs | CRITICAL | Type mismatch = runtime crash when backend changes. |
| 5 | Enum values constrained (union types, not free strings) | MINOR | `'active' \| 'inactive'` not `string` for status fields. |

### State Management (6 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | React Query for ALL server data | MAJOR | Server state in useState = no caching, no revalidation, no dedup. |
| 2 | Zustand ONLY for UI state | MAJOR | Mixing server data into Zustand = stale data, manual refetching. |
| 3 | No `useState` for API data | MAJOR | useState for server data = cache miss on every mount. |
| 4 | Query keys include tenant identifiers | BLOCKER | Missing workspaceId in key = cache collision across tenants. |
| 5 | Mutations invalidate correct query keys | CRITICAL | Wrong invalidation = stale list after create/update/delete. |
| 6 | Optimistic updates have rollback handlers | MAJOR | Failed optimistic update without rollback = ghost data in UI. |

### Components (8 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | `UnifiedDataTable` for list views | MAJOR | Custom table markup = inconsistent UX, missing features. |
| 2 | Column definitions in separate file | MINOR | Inline columns clutter the component and prevent reuse. |
| 3 | Forms use `react-hook-form` + Zod | MAJOR | Manual form state = re-render storms + no validation. |
| 4 | Loading state present (skeleton/spinner) | MAJOR | Missing loading state = flash of empty content. |
| 5 | Empty state present (no data message) | MAJOR | Blank screen when empty = user thinks app is broken. |
| 6 | Error state present (API failure message) | CRITICAL | Unhandled error = white screen or cryptic error. |
| 7 | Toast on mutation success/failure (sonner) | MINOR | Silent mutations = user unsure if action worked. |
| 8 | Component under 200 lines (split if larger) | MINOR | Oversized component = hard to test, hard to reuse. |

### Performance (5 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | No fetch-all patterns (paginate or virtualize) | CRITICAL | Fetching 50k recipients client-side = browser crash. |
| 2 | Chunked processing for >1000 client-side items | MAJOR | Processing large arrays blocks the main thread. |
| 3 | No unnecessary re-renders (React.memo, useMemo where needed) | MINOR | Excessive re-renders = laggy UI on lower-end devices. |
| 4 | Images optimized (next/image, lazy loading) | MINOR | Unoptimized images = slow page load. |
| 5 | Dynamic imports for heavy components | MINOR | Loading chart library on every page = bundle bloat. |

### Multi-Tenant UX (4 items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Progressive complexity applied (UC1 simple, UC3 full) | CRITICAL | UC1 user seeing MSSP controls = confusion + support tickets. |
| 2 | Workspace selector only when `workspaceCount > 1` | MAJOR | Single-workspace user does not need a switcher. |
| 3 | Domain tabs only when `domainCount > 1` | MAJOR | Single-domain user does not need domain tabs. |
| 4 | Person column visible for UC2+ only | MAJOR | Person is meaningless for UC1 (1:1 with recipient). |

---

## MULTI-TENANT REVIEW CHECKLIST (16 Items)

These checks apply to EVERY PR. Multi-tenancy is not a feature flag; it is the foundation.

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Every new query includes `workspaceId` or `domainId` filter | BLOCKER | Missing filter = cross-tenant data exposure. |
| 2 | tenantContext resolved from Redis (not DB join on every request) | CRITICAL | DB join per request = 2-5ms overhead on every hot path. |
| 3 | Subscription status checked (`active` or `trialing` only) | CRITICAL | Inactive subscription must block mutations. |
| 4 | Additive limit check on imports/bulk-create | CRITICAL | `existing + incoming <= limit`, prevent over-provisioning. |
| 5 | Person de-duplication for targeting operations | MAJOR | UC2/UC3: one person, multiple recipients = duplicate emails. |
| 6 | Company Library `companyId` on shareable content | MAJOR | Without companyId, content cannot be shared across workspaces. |
| 7 | Blueprint pattern for cross-workspace deployment | MAJOR | Manual replication across workspaces = inconsistency. |
| 8 | Settings inheritance: `useCompanyDefaults` + `overriddenFields[]` | MAJOR | Missing inheritance = MSSP admin must configure each workspace manually. |
| 9 | Progressive complexity in UI (hide UC3 features from UC1) | CRITICAL | Feature overload on simple customers = churn. |
| 10 | Admin permissions: Company Admin vs Workspace Admin scope | CRITICAL | Wrong permission check = privilege escalation. |
| 11 | Cross-workspace training credit considered | MAJOR | Person completes in WS-A, should get credit in WS-B. |
| 12 | Reports de-duplicate by Person (unique headcount) | MAJOR | Inflated counts from recipient-level reporting = inaccurate metrics. |
| 13 | Cache keys include tenant scope (domainId/workspaceId) | BLOCKER | Unscoped cache key = tenant A sees tenant B's cached data. |
| 14 | Redis key TTL set (no infinite-lived keys) | MAJOR | Missing TTL = Redis memory leak over time. |
| 15 | Workspace isolation test exists | CRITICAL | No test = no proof that isolation works. |
| 16 | Domain migration handled (rare but must not break) | MINOR | Domain moves between workspaces ~once/year. Denormalized IDs must update. |

---

## SECURITY REVIEW CHECKLIST (12 Items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Input validation on every endpoint (DTO + Zod/class-validator) | CRITICAL | Unvalidated input = injection + crash + corruption. |
| 2 | SQL injection prevention (parameterized queries, no string concat) | BLOCKER | Raw SQL with user input = database compromise. |
| 3 | XSS prevention in user-generated content (sanitize HTML, escape output) | BLOCKER | Stored XSS = attacker runs JS in other users' browsers. |
| 4 | No `@Public()` on protected endpoints | BLOCKER | Unauthenticated access to tenant data. |
| 5 | Cross-workspace data leak: mismatched workspace header | BLOCKER | Request with workspace-A header accessing workspace-B data. |
| 6 | CORS configuration correct (no wildcard `*` in production) | CRITICAL | Wildcard CORS = any origin can make authenticated requests. |
| 7 | Rate limiting on auth endpoints | CRITICAL | No rate limit = brute force attacks on login/reset. |
| 8 | Secrets not committed (API keys, tokens, passwords) | BLOCKER | Secrets in git = compromised credentials. |
| 9 | File upload validation (type, size, content) | CRITICAL | Unrestricted upload = remote code execution risk. |
| 10 | Admin impersonation: max 1 hour, non-renewable, reason required | CRITICAL | Unbounded impersonation = abuse risk without accountability. |
| 11 | Audit log for every security-relevant action | CRITICAL | No audit = no forensics after incident. |
| 12 | Error messages do not leak stack traces or internal paths | MAJOR | Verbose errors = reconnaissance for attackers. |

---

## PERFORMANCE REVIEW CHECKLIST (10 Items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | No unbounded queries (always LIMIT or pagination) | CRITICAL | SELECT * without LIMIT on 100k rows = OOM. |
| 2 | N+1 queries eliminated (JOIN or batch fetch) | CRITICAL | 100 recipients with 100 SELECT for extensions = 101 queries. |
| 3 | Bulk operations use batch processing (500 per batch) | MAJOR | Row-by-row processing = 100x slower than batch. |
| 4 | >1000 items -> BullMQ (not in-request) | CRITICAL | Long request = HTTP timeout + blocked worker thread. |
| 5 | Redis caching for read-heavy paths | MAJOR | DB hit on every read = unnecessary latency. |
| 6 | Cache invalidation correct (mutation clears related keys) | MAJOR | Stale cache = users see outdated data. |
| 7 | Database indexes match query patterns | CRITICAL | Missing index = full table scan on every query. |
| 8 | No `SELECT *` (select only needed columns) | MINOR | Extra columns = wasted I/O and memory. |
| 9 | Frontend: no fetch-all (paginate or virtualize large lists) | CRITICAL | Loading 50k rows client-side = browser freeze. |
| 10 | Frontend: heavy components use dynamic imports | MINOR | Chart/editor libraries in main bundle = slow initial load. |

---

## BULLMQ / JOB PROCESSING REVIEW (8 Items)

| # | Check | Severity | Why |
|---|-------|----------|-----|
| 1 | Processor extends `BaseProcessor` | CRITICAL | Skipping BaseProcessor = no job logging, no dead letter handling. |
| 2 | Job payload includes `tenantContext` | BLOCKER | Job without tenant context = cannot scope queries or enforce limits. |
| 3 | Job deduplication via `jobId` parameter | MAJOR | Duplicate job submission = double processing, data corruption. |
| 4 | Dead letter queue handling on final failure | MAJOR | Silent failure = lost jobs with no visibility. |
| 5 | Progress reporting via Redis key (`job:{jobId}:progress`) | MAJOR | No progress = user stares at spinner with no feedback. |
| 6 | Batch size appropriate (typically 500) | MINOR | Too small = overhead per batch. Too large = memory pressure. |
| 7 | Job retry configuration (typically 3 attempts with backoff) | MAJOR | No retry = transient failures become permanent failures. |
| 8 | SSE endpoint exists for job progress streaming | MAJOR | Client polling = wasteful. SSE = real-time progress. |

---

## REVIEW WORKFLOW

### Before You Start

1. Read the PR description. If there is no description, request one before reviewing.
2. Check the linked issue/ticket. Understand the requirements.
3. Check which customer types are affected (UC1/UC2/UC3).
4. Check if a planning document exists. If this is a complex feature without a plan, flag it.

### During Review

1. **Schema first** — Does the data model support all three customer types?
2. **API second** — Is every endpoint tenant-scoped and audited?
3. **Frontend third** — Does the UI respect progressive complexity?
4. **Tests fourth** — Is multi-tenant isolation tested?
5. **Config last** — Any secrets, env vars, or breaking changes?

### After Review

1. Summarize your findings by severity:
   ```
   ## Review Summary
   - BLOCKER: 0
   - CRITICAL: 2
   - MAJOR: 4
   - MINOR: 3
   - NIT: 1

   ### Must fix before merge:
   (none)

   ### Must fix before deploy:
   1. [CRITICAL] Missing workspaceId filter in dashboard query (service.ts:42)
   2. [CRITICAL] No pagination on recipient list endpoint (repository.ts:18)

   ### Should fix in this PR:
   1. [MAJOR] Business logic in controller (controller.ts:25)
   ...
   ```

2. If there are BLOCKERs: Request Changes.
3. If there are CRITICALs only: Approve with comments (fix before deploy).
4. If only MAJOR and below: Approve.
5. If only NIT: Approve and explicitly say "All NITs are optional."

---

## CODE SMELL DETECTION PATTERNS

### Backend Smells

| Smell | What To Look For | Fix |
|-------|-----------------|-----|
| Fat Controller | >20 lines in a controller method | Extract to service |
| Tenant Bypass | Query without workspaceId/domainId in WHERE | Add tenant filter |
| Sync Bulk | In-request loop processing >100 items | Move to BullMQ job |
| Raw SQL Concat | String interpolation in SQL | Use parameterized queries |
| Missing Audit | POST/PATCH/DELETE without @Audit | Add decorator |
| God Service | Service with >500 lines or >10 methods | Split by subdomain |
| Cache Miss | Read-heavy path without Redis caching | Add cache + TTL |
| Silent Failure | catch block that swallows error | Log or re-throw |
| Config in Code | Hardcoded URL, limit, or feature flag | Extract to config/env |
| Circular Dep | Service A imports Service B which imports Service A | Extract shared logic to a third service |

### Frontend Smells

| Smell | What To Look For | Fix |
|-------|-----------------|-----|
| useState for API Data | `const [data, setData] = useState()` with fetch in useEffect | Use React Query |
| Missing Error Boundary | Component with async data but no error handling | Add error state |
| Prop Drilling | >3 levels of passing the same prop | Use context or Zustand |
| Inline Styles | `style={{ ... }}` instead of Tailwind classes | Convert to Tailwind |
| Fetch in Render | API call inside component body (not in hook) | Extract to custom hook |
| Unkeyed List | `.map()` without stable `key` prop | Add unique key |
| Magic Strings | Hardcoded API URLs or route paths | Use constants |
| Giant Form | Form component >300 lines | Split into step components |
| No Debounce | Search input firing API on every keystroke | Add debounce (300ms) |
| Stale Closure | useEffect/useCallback with missing dependencies | Fix dependency array |

---

## CONDITIONAL REVIEW TRIGGERS

Certain types of changes require additional scrutiny. Apply these checks when the condition is met.

### If PR Touches Recipients

- [ ] Person de-duplication considered (UC2: intra-workspace, UC3: cross-workspace)
- [ ] Extension tables updated if adding product-specific data
- [ ] Recipient count cache invalidated after CUD operations
- [ ] Bulk operations respect the async threshold (>1000 -> BullMQ)
- [ ] Import flow uses staging table + preview + commit pattern

### If PR Touches Campaigns / Announcements / Vishing

- [ ] Blueprint pattern supported for UC3 deployment
- [ ] De-duplication by Person for targeting
- [ ] Domain-specific sender config resolved correctly
- [ ] Training assignment linked if applicable
- [ ] SSE progress for long-running sends

### If PR Touches Training

- [ ] Cross-workspace training credit handled (UC3)
- [ ] `TrainingCompletionType.CROSS_WS_CREDIT` considered
- [ ] Company Library tier for shareable training content
- [ ] Quiz/completion criteria from settings inheritance

### If PR Touches Settings

- [ ] Settings inheritance: company defaults -> workspace overrides
- [ ] `overriddenFields[]` updated when workspace overrides a field
- [ ] Always-workspace-specific fields NOT inherited (SSO, domains, branding)
- [ ] Cache invalidated for all affected workspaces

### If PR Touches Admin Panel

- [ ] AdminJwtGuard + AdminMfaGuard applied
- [ ] Impersonation: max 1 hour, non-renewable, reason required
- [ ] Every action logged with `actorType: 'admin_impersonation'`
- [ ] Company Admin vs Workspace Admin permission boundary enforced

### If PR Adds a New Module

- [ ] Module follows `src/modules/{feature}/` structure
- [ ] Controller, service, repository, DTO all present
- [ ] Module registered in app.module.ts
- [ ] E2E test file created
- [ ] Swagger documentation added

---

## MASTER CHECKLIST — Run on Every PR

This is the minimum viable review. Every item MUST be checked.

**Tenant Isolation (non-negotiable)**
- [ ] Every new query includes workspaceId or domainId
- [ ] tenantContext resolved and checked in service layer
- [ ] No cross-workspace data exposure possible
- [ ] Cache keys scoped by tenant identifiers

**Data Integrity**
- [ ] Schema has all three tenant IDs (companyId, workspaceId, domainId)
- [ ] domainId indexed on new tables
- [ ] Soft delete present (deletedAt)
- [ ] Cascade rules explicit
- [ ] Transactions for multi-table writes

**Security**
- [ ] Input validation on every endpoint
- [ ] No SQL injection vectors
- [ ] No XSS in user-generated content
- [ ] No @Public on protected endpoints
- [ ] Secrets not in source code

**Quality**
- [ ] No `any` types
- [ ] No N+1 queries
- [ ] No unbounded queries
- [ ] Tests cover happy path + error paths
- [ ] Multi-tenant isolation test exists

**Observability**
- [ ] @Audit on mutations
- [ ] BullMQ processors extend BaseProcessor
- [ ] Error messages are safe (no internal leaks)
- [ ] Console.log removed (use proper logger)

**UX (frontend PRs)**
- [ ] Loading, empty, and error states present
- [ ] Progressive complexity applied
- [ ] Toast on mutations
- [ ] Forms validated with Zod

**Customer Types**
- [ ] UC1: Does this work without multi-tenant UI?
- [ ] UC2: Does this handle multiple domains in one workspace?
- [ ] UC3: Does this respect workspace isolation + company-level features?
