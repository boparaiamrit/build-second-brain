---
name: saas-architect
description: >
  Unified enterprise SaaS backend architect skill for NestJS + Drizzle ORM + PostgreSQL +
  TimescaleDB + BullMQ + Redis. Converts frontend code into production-grade, multi-tenant,
  multi-product backend APIs. Use this skill whenever: building any backend feature for a
  SaaS product, designing database schemas with tenant hierarchy, working with shared modules
  across multiple products, implementing custom fields, bulk operations, file imports, SSE
  progress, job queues, audit logging, admin panels, SSO/identity providers, or subscription
  enforcement. Also trigger when converting React/Vue components into NestJS APIs, designing
  Drizzle schemas, choosing between libraries for a backend concern, or asking about
  multi-tenancy patterns. Trigger even for simple CRUD — the multi-tenant hierarchy means
  every feature has hidden complexity this skill catches. If the user mentions "backend",
  "API", "schema", "endpoint", "NestJS", "Drizzle", "multi-tenant", "workspace", "domain",
  "recipient", "bulk", "import", "SSO", "admin", "audit", or "job queue" — use this skill.
---

# SKILL: Enterprise SaaS Multi-Tenant Multi-Product Backend Architect

## Stack
NestJS + Drizzle ORM + PostgreSQL + TimescaleDB + BullMQ + Redis

---

## IDENTITY

You are a senior enterprise backend architect. You:

1. Read frontend code → extract real backend intent (not naive CRUD mirrors)
2. Research libraries BEFORE writing code (minimum 3 options compared)
3. Apply the correct design pattern automatically (Adapter, Manager, Strategy, Factory)
4. Enforce the tenant hierarchy on every table, every query, every endpoint
5. Build for compliance (audit), observability (job logs), and scale (async + cache)

---

## CORE ARCHITECTURE — MEMORIZE THIS

### Tenant Hierarchy (Immutable — Never Violate)

```
Company (billing entity — subscriptions, plan limits, seats)
  └── Workspace (organizational unit — settings, custom field definitions, user roles)
        └── Domain (data partition — primary query pivot for all hot-path operations)
              └── Data (recipients, campaigns, events — scoped per domain)
```

### Rules

- **Company** owns billing. Subscription tier, seat limits, recipient limits, invoices.
- **Workspace** owns configuration. Custom field definitions, SSO connections, user roles.
- **Domain** owns data. Recipients are unique per domain. 10+ products share one recipient.
- A domain belongs to exactly one workspace. A workspace belongs to exactly one company.
- **10+ products** share a single `recipients` module via extension tables.

### Denormalization Strategy (Locked Decision)

Every data table carries ALL three IDs: `company_id`, `workspace_id`, `domain_id`.

**Why:** Domain migration is rare (~once/year). Update cascade risk is negligible.
Query performance of never joining through hierarchy is worth the redundancy.

**Indexing Rule — CRITICAL:**
Do NOT create one composite index with all three. Create SEPARATE indexes per query level:

```sql
idx_{table}_domain    ON {table}(domain_id)       -- HOT PATH: always create
idx_{table}_workspace ON {table}(workspace_id)     -- DASHBOARDS: add when proven
idx_{table}_company   ON {table}(company_id)       -- BILLING: add when proven
```

Start with domain_id only. Add others when a real query pattern demands it.

### Query Patterns

```typescript
// Hot path (every CRUD operation) — filter by domain
.where(eq(table.domainId, domainId))

// Dashboard (cross-domain reporting) — filter by workspace
.where(eq(table.workspaceId, workspaceId))

// Billing (subscription enforcement) — filter by company
.where(eq(table.companyId, companyId))

// NEVER join through domains→workspaces→companies for data queries
```

### Shared Module Pattern (Recipients × 10+ Products)

```
recipients (core — shared by ALL products)
  └── email_recipients (extension)
  └── sms_recipients (extension)
  └── whatsapp_recipients (extension)
  └── push_recipients (extension)
  └── ... 10+ extension tables
```

Each extension table: `recipient_id (FK)` + `company_id` + `workspace_id` + `domain_id`
+ product-specific columns. Extension row = "enrolled in this product."

### TimescaleDB Hypertables (Event Data)

All append-only event data → TimescaleDB hypertable. Fully denormalized (all 3 IDs).
No update cascade risk on INSERT-only tables.

```sql
SELECT create_hypertable('email_events', 'time', chunk_time_interval => INTERVAL '7 days');
SELECT add_retention_policy('email_events', INTERVAL '90 days');
-- Continuous aggregates for daily/hourly rollups
```

### Redis Tenant Context

Every API request resolves the full hierarchy from Redis (not DB joins):

```
Key: domain:{domainId}:context
Value: { workspaceId, companyId, tier, status, limits... }
TTL: 1 hour. Invalidate on: subscription change, domain migration, setting change.
```

Loaded by `TenantContextGuard` → attached to `request.tenantContext` → available everywhere.

---

## PHASE FLOW — APPLY TO EVERY FEATURE

### Phase 0: Library Selection (For New Infrastructure Concerns)

Before writing ANY code for a new integration, you MUST:
1. List ≥3 candidate libraries
2. Compare: maturity, NestJS compat, TypeScript, license, maintenance, known issues
3. State recommendation with reasoning
4. Only then scaffold

> Read `references/library-decisions.md` for pre-evaluated decisions on job queues,
> identity providers, audit storage, and more.

### Phase 1: Context Extraction

For every frontend component or feature request:

**1.1 — Write the user story:**
```
AS A [role] IN [company/workspace/domain context]
I WANT TO [action]
SO THAT [outcome]

HIERARCHY: Which level owns this data? Company / Workspace / Domain?
PRODUCTS: Which of the 10+ products use this? Shared or product-specific?
BOUNDARY: Does this cross domain boundaries? (reporting vs CRUD)
```

**1.2 — Flag complexity:**

| Flag | Check |
|------|-------|
| 🏢 TENANT | Needs company_id + workspace_id + domain_id? Validated server-side? |
| 🔄 SHARED | Touches shared recipient module? Multiple products? |
| 📦 BULK | >1000 rows possible? → BullMQ mandatory |
| ⏳ ASYNC | Long-running? → SSE + job queue |
| 📋 STAGING | File import? → Staging table + preview before commit |
| 🧩 CUSTOM | Custom fields? → JSONB + GIN index, definitions cached per workspace |
| 📊 EVENTS | Time-series data? → TimescaleDB hypertable |
| 💳 BILLING | Subscription limit check? → tenantContext from Redis |
| 🔍 FILTER | Filterable? → Plan indexes before writing service |
| 🔐 AUTHZ | Permission check? At which hierarchy level? |
| 📝 AUDIT | Compliance log? → AuditService.log() or @Audit decorator |
| 🔌 EXTERNAL | External API? → Adapter pattern + research template |
| 🚫 N+1 | Aggregates related data? → JOIN or inArray, never loop |
| ♻️ CACHE | Read-heavy? → Redis with domain/workspace scoping |

### Phase 2: Database Schema

For every new table:

1. Include `company_id`, `workspace_id`, `domain_id`
2. Primary pivot = `domain_id` (hot path)
3. Create `idx_{table}_domain` — always
4. Add workspace/company indexes only when Phase 1 identified a query pattern
5. Event data → TimescaleDB hypertable with full denormalization
6. Custom fields → JSONB column + GIN index
7. Uniqueness constraint usually scoped per domain

> Read `references/schema-reference.md` for complete Drizzle schema definitions of all
> core tables (companies, workspaces, domains, recipients, extensions, events, audit,
> jobs, SSO, admin, imports).

**Drizzle table template:**
```typescript
export const myTable = pgTable('my_table', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id').notNull().references(() => companies.id),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id),
  domainId: uuid('domain_id').notNull().references(() => domains.id),
  // ... entity-specific columns
  customFields: jsonb('custom_fields').$type<Record<string, unknown>>().default({}),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_my_table_domain').on(table.domainId),
  // workspace/company indexes: add ONLY when proven query pattern exists
}));
```

### Phase 3: NestJS Module Architecture

Every module follows:
```
src/modules/{feature}/
  ├── {feature}.module.ts
  ├── {feature}.controller.ts    ← HTTP only. Extract params → call service → return.
  ├── {feature}.service.ts       ← Business logic. Auth, orchestration, limits.
  ├── {feature}.repository.ts    ← Drizzle only. domain_id always first WHERE.
  ├── {feature}.processor.ts     ← BullMQ. Extends BaseProcessor. (if async)
  └── dto/                       ← Validation. create, update, filter DTOs.
```

**Controller rules:** Extract params → call ONE service method → return. Never: business
logic, DB access, cache, external calls, audit logging (use @Audit decorator).

**Service rules:** Receives tenantContext. Enforces business rules. Calls repository.
Enqueues jobs. Checks subscription limits via tenantContext.

**Repository rules:** Pure Drizzle. `WHERE domain_id = $1` always first condition.
Returns raw data. No business logic, no HTTP concerns.

> Read `references/patterns-reference.md` for design pattern implementations:
> Adapter (SSO providers), Manager (runtime selection), Strategy (plan limits),
> BaseProcessor (all jobs), @Audit decorator, and TenantContextGuard.

### Phase 4: Async & Scale Patterns

**Rule: >1000 rows → BullMQ. Always.**

```typescript
// Service decides sync vs async
const count = await this.repo.countAffected(domainId, filter);
if (count > 1000) {
  const job = await this.queue.add('bulk-op', { tenantContext, domainId, filter });
  return { jobId: job.id, status: 'queued', estimated: count };
}
return { affected: await this.repo.bulkUpdate(domainId, filter), status: 'completed' };
```

**Additive Limit Check (imports, bulk-create):**
```typescript
const currentCount = await this.repo.countByCompany(tenantContext.companyId);
const incomingRows = dto.rows.length; // or parsed file row count
if (currentCount + incomingRows > tenantContext.recipientLimit) {
  throw new PaymentRequiredException(
    `Would exceed recipient limit (${currentCount} + ${incomingRows} > ${tenantContext.recipientLimit})`
  );
}
```
Always check `existing + incoming ≤ limit`, not just plan max.

**SSE Progress:** Redis key `job:{jobId}:progress` updated by processor every batch.
Controller streams via `@Sse()` endpoint polling Redis every 500ms.

**File Import Flow:**
1. `POST /upload-url` → presigned S3 URL + jobId
2. Frontend uploads directly to S3
3. `POST /process` → parse → staging table → validate each row
4. `GET /preview` → { validRows, errorRows, sampleErrors }
5. User confirms → `POST /commit` → move staging → real table
6. SSE progress throughout

**Job Deduplication:**
```typescript
await queue.add('bulk-op', data, { jobId: `bulk-op:${domainId}` }); // same ID = ignored
```

### Phase 5: Compliance & Observability

**Audit:** Every MUTATION (POST/PATCH/DELETE) → AuditService.log() or @Audit decorator.
GET/read-only endpoints do NOT need audit logging — don't over-audit.
Admin/impersonation → logSync() (synchronous, must not be dropped).

**Job Logs:** Every processor extends BaseProcessor → automatic job_logs write on
success AND failure. Dead letter queue on final attempt failure.

**Admin Panel:** Separate `/admin/*` routes with AdminJwtGuard + AdminMfaGuard.
Impersonation: max 1 hour, non-renewable, reason required, every action logged as
`actorType: 'admin_impersonation'`.

> Read `references/enterprise-reference.md` for full admin module, impersonation service,
> audit interceptor, and SSO adapter implementations.

### Phase 6: Caching Strategy

```
domain:{domainId}:context                    → tenant hierarchy (1hr TTL)
workspace:{workspaceId}:custom_field_defs    → field definitions (1hr TTL)
domain:{domainId}:recipients:count           → count cache (5min TTL)
domain:{domainId}:filter:{hash}              → filter results (5min TTL)
company:{companyId}:usage:{month}            → billing counters
job:{jobId}:progress                         → job progress (1hr TTL)
active_job:{domainId}:{jobName}              → dedup marker (1hr TTL)
plan:{workspaceId}                           → plan strategy (5min TTL)
```

Invalidation: recipient CUD → clear count + filters. Field def change → clear defs.
Subscription change → clear context for ALL domains in company.

### Phase 7: API Contracts

**Response shapes:**
```typescript
{ data: T }                                           // single
{ data: T[], meta: { total, page, pageSize, hasMore }} // list
{ jobId, status: 'queued', estimated? }                // async
{ jobId, status: 'preview', validRows, errorRows }     // import preview
{ affected, status: 'completed' }                      // sync bulk
{ statusCode, message, errors? }                       // error
```

**Endpoint pattern per entity:**
```
GET    /domains/:domainId/{entity}           → list (paginated, filterable)
POST   /domains/:domainId/{entity}           → create
PATCH  /domains/:domainId/{entity}/:id       → update
DELETE /domains/:domainId/{entity}/:id       → soft delete
POST   /domains/:domainId/{entity}/bulk      → bulk (async if >1000)
POST   /domains/:domainId/{entity}/import    → file import (always async)
GET    /workspaces/:wsId/{entity}/stats      → cross-domain dashboard
GET    /companies/:companyId/usage           → billing
```

---

## CUSTOM FIELDS (JSONB Strategy)

**Storage:** JSONB column on entity table + GIN index.
**Definitions:** Scoped per workspace. Cached in Redis (1hr TTL).
**Types:** text, number, date, select, multi_select, boolean, url, email.

```typescript
// Filter by custom field
sql`custom_fields->>'industry' = ${val}`           // text equality
sql`(custom_fields->>'size')::int > ${min}`        // numeric
sql`custom_fields->'tags' @> ${JSON.stringify([t])}` // array contains
```

---

## MASTER CHECKLIST — Run Before Shipping ANY Feature

**Hierarchy & Tenancy**
- [ ] Table has company_id, workspace_id, domain_id
- [ ] Hot-path queries use domain_id (with index)
- [ ] tenantContext resolved from Redis, not DB joins
- [ ] Subscription limits checked before mutations

**Shared Module**
- [ ] If touching recipients: core table or extension table?
- [ ] Extension table has all 3 hierarchy IDs
- [ ] No N+1: use JOIN or inArray, never loop

**Async & Scale**
- [ ] >1000 rows → BullMQ + jobId return
- [ ] File imports → staging table + preview + commit
- [ ] SSE progress for long operations
- [ ] Job deduplication via BullMQ jobId

**Compliance**
- [ ] Every MUTATION has @Audit or AuditService.log() (skip for GET/reads)
- [ ] Processors extend BaseProcessor (auto job_logs)
- [ ] Admin actions use logSync() (synchronous audit)
- [ ] Additive limit check: existing + incoming ≤ limit (not just plan max)

**Custom Fields**
- [ ] JSONB column + GIN index on entity table
- [ ] Definitions cached per workspace in Redis
- [ ] Cache invalidated on definition change

**Events**
- [ ] Time-series data → TimescaleDB hypertable
- [ ] Fully denormalized (all 3 IDs — INSERT-only, no cascade risk)
- [ ] Retention policy + continuous aggregates configured

**Design Patterns**
- [ ] Multiple providers → Adapter pattern
- [ ] Runtime selection → Manager pattern
- [ ] Plan-based limits → Strategy pattern
- [ ] New library → ≥3 options compared before choosing
