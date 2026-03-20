# Code Review Checklist — Copy-Paste Into PR Comments

> Copy the relevant sections into your PR review comment. Check items as you review.
> Each item includes a severity marker and a "why" so junior reviewers understand the reasoning.

---

## How To Use This Checklist

1. Copy the **Master Checklist** section into every PR review
2. Copy **conditional sections** based on what the PR touches
3. Check each box as you verify the item
4. For any unchecked item, leave a review comment with the severity tag
5. Summarize findings at the top using the Review Summary template

---

## Review Summary Template

```markdown
## Review Summary

| Severity | Count |
|----------|-------|
| BLOCKER  | 0     |
| CRITICAL | 0     |
| MAJOR    | 0     |
| MINOR    | 0     |
| NIT      | 0     |

### Verdict: APPROVE / REQUEST CHANGES / APPROVE WITH COMMENTS

### Blocking Issues
(none — or list BLOCKERs)

### Must Fix Before Deploy
(none — or list CRITICALs)

### Should Fix In This PR
(none — or list MAJORs)

### Consider Fixing
(none — or list MINORs and NITs)
```

---

## Master Checklist (Every PR)

Copy this entire section into every review.

### Tenant Isolation

- [ ] **[BLOCKER]** Every new query includes `workspaceId` or `domainId` filter
  - *Why: Missing filter returns data from ALL tenants. In MSSP (UC3), one subsidiary sees another's data.*
- [ ] **[BLOCKER]** No cross-workspace data exposure possible
  - *Why: Workspace isolation is sacred. Subsidiary A must never see Subsidiary B's recipients, campaigns, or reports.*
- [ ] **[CRITICAL]** `tenantContext` resolved and checked in service layer
  - *Why: Without tenantContext, the service cannot enforce subscription limits or scope queries correctly.*
- [ ] **[BLOCKER]** Cache keys include tenant scope (`domainId`, `workspaceId`)
  - *Why: Unscoped cache key `recipients:count` returns Tenant A's count to Tenant B.*

### Schema & Data Model

- [ ] **[BLOCKER]** New tables have `companyId`, `workspaceId`, `domainId`
  - *Why: The tenant hierarchy is denormalized onto every table. This is the locked architecture decision. No exceptions.*
- [ ] **[CRITICAL]** `domainId` has a dedicated index (`idx_{table}_domain`)
  - *Why: Hot-path queries always filter by domainId. Without an index, every query does a full table scan.*
- [ ] **[MAJOR]** Soft delete present (`deletedAt` column, nullable timestamp)
  - *Why: Hard deletes lose audit trail. Compliance and data recovery require soft delete.*
- [ ] **[CRITICAL]** Cascade rules explicit on foreign keys
  - *Why: Default cascade behavior varies by ORM. Implicit cascade can orphan records or delete tenant data.*
- [ ] **[MAJOR]** Transactions used for multi-table writes
  - *Why: Writing to 2+ tables without a transaction = partial writes on failure = data inconsistency.*

### Security

- [ ] **[CRITICAL]** Input validation on every endpoint (DTO with Zod or class-validator)
  - *Why: Unvalidated input is the root cause of injection, crashes, and data corruption.*
- [ ] **[BLOCKER]** No SQL injection vectors (parameterized queries only)
  - *Why: String concatenation in SQL = database compromise. Always use query parameters.*
- [ ] **[BLOCKER]** No XSS in user-generated content
  - *Why: Stored XSS in recipient notes, campaign names, etc. = attacker runs JS in other users' sessions.*
- [ ] **[BLOCKER]** No `@Public()` on protected endpoints
  - *Why: @Public skips all authentication. One misplaced decorator = open access to tenant data.*
- [ ] **[BLOCKER]** No secrets in source code (API keys, tokens, passwords)
  - *Why: Secrets in git history are permanent. Even after removal, they exist in every clone.*

### Code Quality

- [ ] **[MAJOR]** No `any` type anywhere in TypeScript
  - *Why: `any` disables type checking. One `any` cascades into unsafe code downstream.*
- [ ] **[CRITICAL]** No N+1 queries (use JOIN or `inArray`)
  - *Why: Looping queries = O(n) database calls. 100 recipients = 100 queries instead of 1.*
- [ ] **[CRITICAL]** No unbounded queries (LIMIT on every SELECT)
  - *Why: SELECT without LIMIT on a table with 100k rows = out-of-memory crash.*
- [ ] **[CRITICAL]** Tests cover happy path AND at least 2 error paths
  - *Why: Happy path tests prove the feature works. Error path tests prove it fails gracefully.*
- [ ] **[CRITICAL]** Multi-tenant isolation test exists
  - *Why: No test for isolation = no proof that workspace A cannot see workspace B's data.*

### Observability

- [ ] **[CRITICAL]** `@Audit` decorator on mutation endpoints (POST/PATCH/DELETE)
  - *Why: Compliance requires a trail of who changed what, when. GET/read-only endpoints are exempt.*
- [ ] **[CRITICAL]** BullMQ processors extend `BaseProcessor`
  - *Why: BaseProcessor provides automatic job logging and dead letter queue. Custom processing bypasses both.*
- [ ] **[MAJOR]** Error messages do not leak internal state
  - *Why: Stack traces, SQL queries, or file paths in error responses = reconnaissance for attackers.*
- [ ] **[MINOR]** No `console.log` in production code (use NestJS Logger)
  - *Why: console.log has no log level, no structured output, no integration with log aggregation.*

### UX (Frontend PRs Only)

- [ ] **[MAJOR]** Loading state present (skeleton or spinner)
  - *Why: Missing loading state = flash of empty content. User thinks the app is broken.*
- [ ] **[MAJOR]** Empty state present (no data message with action)
  - *Why: Blank screen when empty = user does not know what to do next.*
- [ ] **[CRITICAL]** Error state present (API failure message)
  - *Why: Unhandled error = white screen. User cannot recover without refreshing.*
- [ ] **[MINOR]** Toast notification on mutation success/failure
  - *Why: Silent mutations = user unsure if their action (save, delete, update) actually worked.*
- [ ] **[MAJOR]** Forms validated with Zod schema
  - *Why: Unvalidated forms send garbage to the backend. Zod catches issues client-side.*

### Customer Types

- [ ] **[CRITICAL]** UC1: Feature works without any multi-tenant UI (zero extra clicks)
  - *Why: UC1 customers have 1 workspace, 1 domain. They should never see workspace selectors or domain tabs.*
- [ ] **[MAJOR]** UC2: Feature handles multiple domains in one workspace
  - *Why: UC2 customers have 1 workspace but N domains. Person de-duplication and domain tabs are required.*
- [ ] **[CRITICAL]** UC3: Feature respects workspace isolation + company-level features
  - *Why: UC3 (MSSP) has N workspaces. Cross-workspace data leak = contract violation. Company Library and Blueprints required.*

---

## Conditional: Schema Changes

> Copy this section when the PR includes database migrations or schema changes.

- [ ] **[CRITICAL]** Migration handles existing data (backfill for new NOT NULL columns)
  - *Why: Adding NOT NULL column without default = migration fails on tables with existing rows.*
- [ ] **[CRITICAL]** Uniqueness constraints scoped per domain (not globally unique)
  - *Why: `email` must be unique per domain, not globally. Two domains can have the same email address.*
- [ ] **[MAJOR]** JSONB columns have GIN index if they will be filtered/queried
  - *Why: Custom field queries on JSONB without GIN index = sequential scan on every query.*
- [ ] **[MAJOR]** Event/time-series data uses TimescaleDB hypertable
  - *Why: Append-only event data benefits from automatic partitioning, retention policies, and continuous aggregates.*
- [ ] **[BLOCKER]** Extension tables (recipient extensions) have `recipientId` FK + all 3 tenant IDs
  - *Why: Shared recipient module demands full denormalization. Missing IDs = cannot scope extension data.*
- [ ] **[MINOR]** No unnecessary composite indexes (separate indexes per query level)
  - *Why: One composite `(companyId, workspaceId, domainId)` index rarely matches real query patterns. Separate indexes are more flexible.*
- [ ] **[MAJOR]** Rollback migration exists and is tested
  - *Why: A migration that cannot be rolled back = stuck deployment if something goes wrong.*

---

## Conditional: API / Controller Changes

> Copy this section when the PR adds or modifies API endpoints.

- [ ] **[MAJOR]** Controller only extracts params and calls ONE service method
  - *Why: Business logic in controller = untestable, unreusable. Controllers are HTTP adapters, nothing more.*
- [ ] **[CRITICAL]** `@Audit` decorator on POST/PATCH/DELETE
  - *Why: Every mutation must be auditable for compliance. GET endpoints are exempt.*
- [ ] **[BLOCKER]** No `@Public()` on endpoints that access tenant data
  - *Why: @Public skips authentication entirely. Tenant data must always require auth.*
- [ ] **[CRITICAL]** DTO validation on request body
  - *Why: Accepting raw `req.body` without validation = type confusion, injection, and corruption.*
- [ ] **[MAJOR]** Response shape matches API contract (`{ data }`, `{ data, meta }`, etc.)
  - *Why: Frontend depends on consistent response shapes. Breaking the contract breaks the UI.*
- [ ] **[BLOCKER]** No direct database access from controller
  - *Why: Controllers must go through the service layer where tenant context and business rules are enforced.*
- [ ] **[MAJOR]** SSE endpoint for long-running operations (>5 seconds)
  - *Why: Client polling wastes bandwidth and adds latency. SSE provides real-time progress.*
- [ ] **[CRITICAL]** Rate limiting on public-facing or auth endpoints
  - *Why: No rate limit on login = brute force. No rate limit on API = denial of service.*

---

## Conditional: Service Layer Changes

> Copy this section when the PR adds or modifies service logic.

- [ ] **[BLOCKER]** `tenantContext` resolved and checked before any data operation
  - *Why: Service without tenant context can access data across tenants.*
- [ ] **[CRITICAL]** Subscription limits enforced with ADDITIVE check
  - *Why: Check `existing + incoming <= limit`, not `incoming <= max`. User with 9,500/10,000 recipients should not import 1,000.*
- [ ] **[CRITICAL]** Async threshold: >1000 items -> BullMQ job (not in-request)
  - *Why: Processing 10k items in-request = 30-second response time = HTTP timeout.*
- [ ] **[MAJOR]** Job deduplication via BullMQ `jobId` parameter
  - *Why: Double-click = two jobs with same payload. `jobId: 'bulk:${domainId}'` prevents duplicates.*
- [ ] **[MAJOR]** Person de-duplication for recipient-touching operations
  - *Why: UC2/UC3: same person across domains. Without de-dup, they get 2 emails for 1 campaign.*
- [ ] **[MAJOR]** Cache invalidation after data mutations
  - *Why: Write without cache clear = stale data. User creates recipient, list still shows old count.*
- [ ] **[CRITICAL]** Error messages safe (no stack traces, SQL, or internal paths)
  - *Why: Detailed errors help attackers map your system internals.*

---

## Conditional: Repository Changes

> Copy this section when the PR adds or modifies database queries.

- [ ] **[CRITICAL]** `domainId` is FIRST condition in WHERE clause
  - *Why: Index scan requires the leading column to be domainId. Wrong order = index miss.*
- [ ] **[CRITICAL]** No N+1: use JOIN or `inArray()`, never loop queries
  - *Why: Loading 100 recipients with extensions = 1 query with JOIN, not 100 queries in a loop.*
- [ ] **[MAJOR]** Batch operations for bulk updates (typically 500 per batch)
  - *Why: Row-by-row UPDATE = 100x slower than batched. Also risks connection pool exhaustion.*
- [ ] **[CRITICAL]** Pagination on all list queries (LIMIT + OFFSET)
  - *Why: Unbounded SELECT on production table with 500k rows = out-of-memory.*
- [ ] **[CRITICAL]** Soft-delete filter applied (`WHERE deletedAt IS NULL`)
  - *Why: Without the filter, "deleted" records still appear in list views and counts.*
- [ ] **[MAJOR]** Transaction wraps multi-table writes
  - *Why: Creating recipient + extension without transaction = orphaned extension row on failure.*

---

## Conditional: Frontend Component Changes

> Copy this section when the PR adds or modifies React components.

- [ ] **[MAJOR]** Types defined in `types.ts` within the feature directory
  - *Why: Types scattered across components = import spaghetti and inconsistency.*
- [ ] **[MAJOR]** No `any` type anywhere
  - *Why: Every `any` is a hole in the type system that cascades to downstream consumers.*
- [ ] **[MAJOR]** React Query for server data (not useState + useEffect + fetch)
  - *Why: React Query provides caching, deduplication, background refetch, and error/loading states for free.*
- [ ] **[BLOCKER]** Query keys include tenant identifiers (`workspaceId`, `domainId`)
  - *Why: Missing identifier in query key = cache returns Workspace A data to Workspace B.*
- [ ] **[CRITICAL]** Mutations invalidate correct query keys
  - *Why: Create recipient without invalidating `['recipients', domainId]` = stale list view.*
- [ ] **[MAJOR]** `UnifiedDataTable` for all list views
  - *Why: Custom table markup = inconsistent sorting, filtering, pagination, column persistence.*
- [ ] **[MAJOR]** Forms use `react-hook-form` + Zod resolver
  - *Why: Manual form state = re-render on every keystroke. Zod = runtime validation.*
- [ ] **[CRITICAL]** Progressive complexity: UC1 sees simple UI
  - *Why: UC1 user seeing workspace selector, domain tabs, and Person column = confusion.*

---

## Conditional: Recipients / People

> Copy this section when the PR touches the recipients module or Person entity.

- [ ] **[MAJOR]** Person de-duplication considered
  - *Why: UC2 — same person has `john@jio.com` and `john@jiosaavn.com`. Must be treated as ONE person.*
- [ ] **[MAJOR]** Extension tables updated if adding product-specific data
  - *Why: Recipients are shared across 10+ products. Product data goes in extension tables, not core.*
- [ ] **[MAJOR]** Recipient count cache invalidated after CUD
  - *Why: `domain:{domainId}:recipients:count` becomes stale after create/update/delete.*
- [ ] **[CRITICAL]** Bulk operations respect async threshold (>1000 -> BullMQ)
  - *Why: Bulk update of 50k recipients in-request = timeout + blocked worker.*
- [ ] **[MAJOR]** Import uses staging table + preview + commit pattern
  - *Why: Direct import without preview = bad data in production with no way to undo.*
- [ ] **[MAJOR]** PersonMatchSuggestion scope set correctly
  - *Why: UC2 = INTRA_WORKSPACE matching. UC3 = CROSS_WORKSPACE matching. Wrong scope = missed or false matches.*

---

## Conditional: Campaigns / Announcements / Vishing

> Copy this section when the PR touches campaign, announcement, or vishing features.

- [ ] **[MAJOR]** Blueprint pattern supported for UC3
  - *Why: MSSP admin creates once, deploys to N workspaces. Without Blueprint = manual duplication.*
- [ ] **[MAJOR]** De-duplication by Person for targeting
  - *Why: One person in 3 domains should receive 1 campaign email, not 3.*
- [ ] **[CRITICAL]** Domain-specific sender config resolved
  - *Why: Each domain has its own sending email/domain. Using wrong sender = SPF/DKIM failure.*
- [ ] **[MAJOR]** Training assignment linked if applicable
  - *Why: Campaign click -> training assignment. Missing link = broken remediation workflow.*
- [ ] **[MAJOR]** SSE progress for sends
  - *Why: Sending to 50k recipients takes minutes. User needs real-time progress, not a spinner.*

---

## Conditional: Training Module

> Copy this section when the PR touches training features.

- [ ] **[MAJOR]** Cross-workspace training credit handled (UC3)
  - *Why: Person completes training in WS-A, should get credit in WS-B via CROSS_WS_CREDIT.*
- [ ] **[MAJOR]** Company Library tier for shareable training content
  - *Why: Without companyId on training content, MSSP admin cannot share across workspaces.*
- [ ] **[MAJOR]** Quiz/completion criteria from settings inheritance
  - *Why: Company sets default pass rate (70%). Workspace can override. Must resolve correctly.*
- [ ] **[MAJOR]** Reporting de-duplicates by Person
  - *Why: "82.5% completed" must be Person-level, not inflated by counting the same person twice.*

---

## Conditional: Settings / Configuration

> Copy this section when the PR touches workspace or company settings.

- [ ] **[MAJOR]** Settings inheritance: company defaults -> workspace overrides
  - *Why: MSSP admin sets company defaults. Each workspace inherits unless explicitly overridden.*
- [ ] **[MAJOR]** `overriddenFields[]` updated when workspace overrides a field
  - *Why: The system must know WHICH fields are overridden to correctly resolve values.*
- [ ] **[CRITICAL]** Always-workspace-specific fields NOT inherited
  - *Why: SSO credentials, phishing domains, sender emails are per-workspace. Inheriting = security risk.*
- [ ] **[MAJOR]** Cache invalidated for all affected workspaces
  - *Why: Changing company default must bust cache for every workspace that inherits it.*

---

## Conditional: Admin Panel

> Copy this section when the PR touches admin functionality.

- [ ] **[CRITICAL]** AdminJwtGuard + AdminMfaGuard applied
  - *Why: Admin endpoints without MFA = compromised admin account = full platform access.*
- [ ] **[CRITICAL]** Impersonation: max 1 hour, non-renewable, reason required
  - *Why: Unbounded impersonation = abuse without accountability. Time-limited + reason = auditability.*
- [ ] **[CRITICAL]** Every action logged with `actorType: 'admin_impersonation'`
  - *Why: Must distinguish "admin acting as user" from "user acting normally" in audit trail.*
- [ ] **[CRITICAL]** Company Admin vs Workspace Admin permission boundary enforced
  - *Why: Workspace Admin should not access other workspaces. Company Admin has cross-workspace access.*
- [ ] **[MAJOR]** Admin `logSync()` used (not async `log()`)
  - *Why: Admin actions are compliance-critical. Async logging can be dropped. Sync ensures persistence.*

---

## Conditional: BullMQ / Job Processing

> Copy this section when the PR adds or modifies job processors.

- [ ] **[CRITICAL]** Processor extends `BaseProcessor`
  - *Why: BaseProcessor auto-logs to job_logs on success AND failure. Custom handling misses both.*
- [ ] **[BLOCKER]** Job payload includes `tenantContext`
  - *Why: Job without tenant context cannot scope queries. All job data operations need tenant IDs.*
- [ ] **[MAJOR]** Job deduplication via `jobId` parameter
  - *Why: `queue.add('op', data, { jobId: 'op:${domainId}' })` prevents duplicate processing.*
- [ ] **[MAJOR]** Dead letter queue handling on final failure
  - *Why: Without dead letter, permanently failed jobs disappear. No visibility, no retry option.*
- [ ] **[MAJOR]** Progress reported via Redis key `job:{jobId}:progress`
  - *Why: Frontend SSE reads this key. No progress key = no progress bar for the user.*
- [ ] **[MAJOR]** Retry configuration: 3 attempts with exponential backoff
  - *Why: Transient failures (network blip, DB connection) resolve on retry. No retry = permanent failure.*

---

## Conditional: New Module

> Copy this section when the PR introduces an entirely new feature module.

- [ ] **[MAJOR]** Module follows `src/modules/{feature}/` directory structure
  - *Why: Consistent structure = predictable navigation. Every dev knows where to find things.*
- [ ] **[MAJOR]** All required files present: module, controller, service, repository, DTOs
  - *Why: Missing layer = missing separation of concerns. Controller without service = business logic in HTTP layer.*
- [ ] **[MAJOR]** Module registered in app.module.ts
  - *Why: Unregistered module = NestJS does not load it. Endpoints return 404.*
- [ ] **[MAJOR]** E2E test file created
  - *Why: New module without tests = no regression safety net. Must test at least CRUD + tenant isolation.*
- [ ] **[MINOR]** Swagger/OpenAPI documentation added
  - *Why: Undocumented API = frontend devs guessing at request/response shapes.*
- [ ] **[MAJOR]** Feature flag wrapping if behind gradual rollout
  - *Why: New module shipped to all customers at once = no rollback option if something breaks.*
