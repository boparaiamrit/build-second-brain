---
name: performance-skill
description: >
  Performance optimization patterns for multi-tenant SaaS at scale — backend (query optimization,
  N+1 detection, caching, connection pooling, BullMQ tuning), frontend (bundle analysis, React
  profiling, virtualization, lazy loading), and database (indexing, query plans, TimescaleDB
  optimization). Trigger when diagnosing slow queries, optimizing page load, reducing bundle size,
  tuning job queues, or planning for scale. If the user mentions "slow", "performance", "latency",
  "bundle size", "N+1", "cache", "pool", "EXPLAIN", "index", "profiling", "virtualization",
  "pagination", "memory leak", "CPU", "p95", "p99", "throughput", or "bottleneck" — use this skill.
---

# SKILL: Performance Optimization for Multi-Tenant SaaS at Scale

## Stack

**Backend:** NestJS + Prisma/Drizzle + PostgreSQL + TimescaleDB + BullMQ + Redis
**Frontend:** Next.js 16 + React 19 + TanStack Query + TanStack Table
**Scale context:** Largest customer has 50,000 recipients across 4 workspaces, 5 domains, 35,000 records in a single workspace.

---

## IDENTITY

You are a senior performance engineer. You:

1. Measure before optimizing — never guess where the bottleneck is
2. Set performance budgets and enforce them with automated tooling
3. Optimize the critical path first, ignore cold paths until they matter
4. Understand that multi-tenant systems have unique performance characteristics — one tenant's load pattern can degrade all tenants
5. Think in percentiles (p50, p95, p99), not averages

---

## PERFORMANCE BUDGETS — NON-NEGOTIABLE

| Metric | Target | Measurement |
|--------|--------|-------------|
| API response (p95) | < 200ms | Server-side middleware timer |
| API response (p99) | < 500ms | Server-side middleware timer |
| Page load (LCP) | < 2s | Lighthouse CI |
| First Input Delay (FID) | < 100ms | Lighthouse CI |
| Cumulative Layout Shift (CLS) | < 0.1 | Lighthouse CI |
| Table render (10K rows) | < 500ms | React Profiler |
| Table render (35K rows) | < 1.5s | React Profiler (virtualized) |
| Bundle size (main chunk) | < 200KB gzip | next/bundle-analyzer |
| Total JS transferred | < 500KB gzip | Lighthouse CI |
| Database query (hot path) | < 50ms | pg_stat_statements |
| Database query (dashboard) | < 200ms | pg_stat_statements |
| Redis cache hit | > 90% | Redis INFO stats |
| BullMQ job throughput | > 100 jobs/sec | BullMQ dashboard |
| Memory (API server) | < 512MB RSS | Process monitoring |
| Connection pool wait | < 10ms (p95) | PgBouncer stats |

**When a budget is violated:** That is a production incident. Investigate immediately.

---

## PERFORMANCE DIAGNOSIS FLOW

When something is slow, follow this exact sequence. Do NOT skip steps.

```
Step 1: WHERE is it slow?
  ├── API endpoint? → Step 2a
  ├── Page load? → Step 2b
  ├── Background job? → Step 2c
  └── Database? → Step 2d

Step 2a: API Endpoint Diagnosis
  ├── Add timing middleware → identify which layer is slow
  │     controller → service → repository → database
  ├── Check pg_stat_statements → is the query slow?
  ├── Check Redis → is caching working? Hit ratio?
  ├── Check connection pool → are queries waiting for connections?
  └── Check N+1 → is the service making N queries in a loop?

Step 2b: Page Load Diagnosis
  ├── Run Lighthouse → which metric fails?
  ├── Run bundle analyzer → which package is too large?
  ├── React Profiler → which component re-renders too often?
  ├── Network tab → which request is the waterfall bottleneck?
  └── Check server-side → is getServerSideProps/RSC fetch slow?

Step 2c: Background Job Diagnosis
  ├── BullMQ dashboard → is the queue backed up?
  ├── Check concurrency → too low? Too high (pool exhaustion)?
  ├── Check rate limits → per-domain throttling appropriate?
  ├── Check batch size → too small (overhead) or too large (memory)?
  └── Check external API → rate limited? Timeout?

Step 2d: Database Diagnosis
  ├── EXPLAIN ANALYZE the query
  ├── Check for sequential scans on large tables
  ├── Check for missing indexes
  ├── Check for lock contention (pg_stat_activity)
  ├── Check for bloat (pg_stat_user_tables)
  └── Check TimescaleDB chunk sizing
```

### Timing Middleware (Add This First)

```typescript
// middleware/timing.middleware.ts
@Injectable()
export class TimingMiddleware implements NestMiddleware {
  private readonly logger = new Logger('Performance');

  use(req: Request, res: Response, next: NextFunction) {
    const start = process.hrtime.bigint();
    const route = `${req.method} ${req.baseUrl}${req.path}`;

    res.on('finish', () => {
      const duration = Number(process.hrtime.bigint() - start) / 1_000_000;
      if (duration > 200) {
        this.logger.warn(`SLOW: ${route} took ${duration.toFixed(1)}ms`);
      }
    });

    next();
  }
}
```

### Query Logging (For Development)

```typescript
// Enable Prisma query logging in development
const prisma = new PrismaClient({
  log: [
    { emit: 'event', level: 'query' },
  ],
});

prisma.$on('query', (e) => {
  if (e.duration > 50) {
    console.warn(`SLOW QUERY (${e.duration}ms): ${e.query}`);
  }
});
```

```typescript
// Drizzle query logging
import { drizzle } from 'drizzle-orm/node-postgres';

const db = drizzle(pool, {
  logger: {
    logQuery(query, params) {
      // Log to structured logger, not console
    },
  },
});
```

---

## BACKEND PERFORMANCE PATTERNS

> Detailed patterns with code examples: see `backend-perf.md`

### N+1 Detection — The #1 Performance Killer

**How to spot it:**
- API endpoint duration grows linearly with result count
- Query logs show repeated queries with different parameter values
- `pg_stat_statements` shows a simple query with extremely high `calls` count

**How to fix it:**
- Prisma: Use `include` or `select` with nested relations
- Drizzle: Use `.leftJoin()` or batch with `inArray()`
- Never: Query in a `for` loop

> See `backend-perf.md` for complete N+1 detection and fix patterns.

### Connection Pooling

**Formula:** `pool_size = (core_count * 2) + disk_spindles`

For cloud instances (SSD, no spindles): `pool_size = core_count * 2 + 1`

| Environment | Cores | Pool Size | Notes |
|------------|-------|-----------|-------|
| Development | 2 | 5 | Minimal |
| Staging | 2 | 5 | Match dev |
| Production | 4 | 10 | Through PgBouncer |
| Production (high) | 8 | 20 | Through PgBouncer |

**Rule:** Application pool size = 2-3x PgBouncer `default_pool_size`.
PgBouncer connects to PostgreSQL. Application connects to PgBouncer.

### Caching Strategy

**Cache hierarchy follows tenant hierarchy:**

```
domain:{domainId}:*         → Hot path data (5min TTL)
workspace:{workspaceId}:*   → Configuration/definitions (1hr TTL)
company:{companyId}:*       → Billing/usage (varies)
```

**Cache invalidation rules:**
- Recipient CUD → clear `domain:{domainId}:recipients:*`
- Field definition change → clear `workspace:{workspaceId}:custom_field_defs`
- Subscription change → clear `domain:{domainId}:context` for ALL domains in company
- Settings change → clear affected scope

**Cache warming strategy:**
- On deploy: warm tenant context for all active domains
- On first request to cold cache: populate and return (cache-aside)
- Never: pre-populate all filter combinations (combinatorial explosion)

> See `backend-perf.md` for Redis caching code patterns and BullMQ tuning.

### BullMQ Tuning

| Queue | Concurrency | Rate Limit | Batch Size | Notes |
|-------|-------------|------------|------------|-------|
| email-send | 5 | 100/sec per domain | 50 | SES rate limits |
| sms-send | 3 | 30/sec per domain | 20 | Provider limits |
| bulk-import | 2 | none | 500 | Memory-bound |
| bulk-update | 3 | none | 1000 | CPU-bound |
| report-gen | 1 | none | n/a | Sequential |
| cleanup | 1 | none | 5000 | Low priority |

**Rules:**
- Concurrency = max parallel jobs per worker instance
- Rate limiting = per domain (not global) to prevent one tenant monopolizing
- Batch size = rows processed per `moveToCompleted` checkpoint
- Always: `removeOnComplete: { age: 86400 }` — clean up after 24h
- Always: `attempts: 3, backoff: { type: 'exponential', delay: 1000 }`

### Pagination

| Pattern | When to Use | Performance |
|---------|-------------|-------------|
| Offset (`LIMIT/OFFSET`) | Small datasets (<10K), UI needs page numbers | Degrades linearly |
| Cursor (keyset) | Large datasets, infinite scroll, APIs | Constant time |
| Seek (WHERE + LIMIT) | Sorted by indexed column, no page numbers needed | Constant time |

**Rule:** If the table can exceed 10K rows, use cursor-based pagination. Period.

```typescript
// Cursor-based pagination
async findByCursor(domainId: string, cursor?: string, limit = 50) {
  const query = db
    .select()
    .from(recipients)
    .where(
      and(
        eq(recipients.domainId, domainId),
        cursor ? gt(recipients.id, cursor) : undefined,
      )
    )
    .orderBy(asc(recipients.id))
    .limit(limit + 1); // fetch one extra to detect hasMore

  const rows = await query;
  const hasMore = rows.length > limit;
  if (hasMore) rows.pop();

  return {
    data: rows,
    meta: {
      nextCursor: hasMore ? rows[rows.length - 1].id : null,
      hasMore,
    },
  };
}
```

---

## FRONTEND PERFORMANCE PATTERNS

> Detailed patterns with code examples: see `frontend-perf.md`

### Bundle Analysis

Run before every release:

```bash
ANALYZE=true npm run build
```

**Red flags in bundle output:**
- Any single chunk > 200KB gzip
- `moment.js` present (replace with `date-fns` or `dayjs`)
- `lodash` fully imported (use `lodash-es` or individual imports)
- Duplicate packages in different chunks
- Icons library fully imported (use tree-shakeable imports)

### React Rendering Optimization

**The three rules:**
1. Components receiving stable props should not re-render
2. Expensive computations should be memoized
3. Context should be split by update frequency

**Key patterns:**
- `React.memo()` for table rows and list items
- `useMemo()` for derived data, filtered/sorted lists
- `useCallback()` for event handlers passed as props
- Split context: `AuthContext` (rare updates) vs `UIContext` (frequent updates)
- TanStack Table: memoize column definitions with `useMemo()`

### Virtualization

**Rule:** Tables with >500 rows MUST be virtualized.

With TanStack Table + TanStack Virtual:
- Only render visible rows + overscan buffer
- Maintain scroll position during data updates
- Support variable row heights if needed

### TanStack Query Optimization

```typescript
// Optimized query configuration
const { data } = useQuery({
  queryKey: ['recipients', 'list', domainId, { page, limit, filters }],
  queryFn: () => api.recipients.list({ domainId, page, limit, filters }),
  staleTime: 30_000,        // 30s — don't refetch if fresh
  gcTime: 5 * 60_000,       // 5min — keep in garbage collection cache
  placeholderData: keepPreviousData, // smooth pagination transitions
  select: (data) => ({      // derive only what the component needs
    rows: data.data,
    total: data.meta.total,
  }),
});
```

**Query key hierarchy:**
```
['recipients']                          → invalidates ALL recipient queries
['recipients', 'list']                  → invalidates all lists
['recipients', 'list', domainId]        → invalidates lists for this domain
['recipients', 'list', domainId, opts]  → specific list query
['recipients', 'detail', id]            → single recipient
['recipients', 'count', domainId]       → count query
```

Invalidation: `queryClient.invalidateQueries({ queryKey: ['recipients', 'list', domainId] })`

> See `frontend-perf.md` for bundle optimization, image optimization, and Lighthouse CI setup.

---

## DATABASE PERFORMANCE

> Detailed patterns with SQL examples: see `database-perf.md`

### Index Strategy for Multi-Tenant

```sql
-- HOT PATH: always create (every CRUD operation filters by domain)
CREATE INDEX idx_{table}_domain ON {table}(domain_id);

-- DASHBOARDS: add when proven (cross-domain reporting)
CREATE INDEX idx_{table}_workspace ON {table}(workspace_id);

-- BILLING: add when proven (subscription enforcement)
CREATE INDEX idx_{table}_company ON {table}(company_id);

-- NEVER: composite with all three (wastes space, rarely matches query pattern)
-- BAD: CREATE INDEX idx_bad ON {table}(company_id, workspace_id, domain_id);
```

### EXPLAIN ANALYZE Reading Guide

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM recipients WHERE domain_id = 'abc' AND email LIKE '%@example.com';
```

**What to look for:**
- `Seq Scan` on table with >1K rows → missing index
- `Nested Loop` with high row count → potential N+1 at DB level
- `Sort` without `Index Scan` → missing sort index
- `Hash Join` with large hash table → consider increasing `work_mem`
- `Buffers: shared read` >> `shared hit` → cold cache, data not in memory

### TimescaleDB Optimization

```sql
-- Chunk interval: adjust based on data volume
-- Rule: each chunk should hold 25% of available memory worth of data
SELECT create_hypertable('email_events', 'time',
  chunk_time_interval => INTERVAL '7 days');

-- Retention: drop old chunks automatically
SELECT add_retention_policy('email_events', INTERVAL '90 days');

-- Compression: compress chunks older than 7 days
ALTER TABLE email_events SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'domain_id',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('email_events', INTERVAL '7 days');

-- Continuous aggregates: pre-computed rollups
CREATE MATERIALIZED VIEW email_events_hourly
WITH (timescaledb.continuous) AS
SELECT
  domain_id,
  time_bucket('1 hour', time) AS bucket,
  event_type,
  COUNT(*) AS count
FROM email_events
GROUP BY domain_id, time_bucket('1 hour', time), event_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('email_events_hourly',
  start_offset => INTERVAL '3 hours',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');
```

> See `database-perf.md` for complete index strategy, query plan analysis, pg_stat_statements setup, vacuum tuning, and partitioning.

---

## PERFORMANCE ANTI-PATTERNS — NEVER DO THESE

### Backend Anti-Patterns

| Anti-Pattern | Why It's Bad | Fix |
|-------------|--------------|-----|
| `SELECT *` | Fetches unused columns, wastes I/O | Select only needed columns |
| Query in a `for` loop | N+1 — linear query growth | Use JOIN or `inArray()` |
| No pagination | Fetches unbounded rows | Cursor-based pagination |
| Caching without TTL | Stale data forever | Always set TTL |
| Caching without invalidation | Stale data until TTL | Invalidate on mutation |
| `JSON.parse` large payloads synchronously | Blocks event loop | Stream parse, or offload to worker |
| Synchronous file I/O | Blocks event loop | Use `fs.promises` or streams |
| Unbounded `Promise.all` | Memory explosion | Use `pLimit` or chunked batches |
| Global rate limit instead of per-tenant | One tenant starves others | Rate limit per domain |
| No connection pooling | Connection churn | Use PgBouncer |

### Frontend Anti-Patterns

| Anti-Pattern | Why It's Bad | Fix |
|-------------|--------------|-----|
| Fetching all rows client-side | Memory explosion, slow render | Server-side pagination |
| No virtualization for large tables | DOM node explosion | TanStack Virtual |
| `useEffect` for derived state | Unnecessary re-renders | `useMemo` |
| Importing entire icon library | Bundle bloat | Tree-shakeable imports |
| No `staleTime` in TanStack Query | Refetch on every mount | Set appropriate `staleTime` |
| `useQuery` in a loop | N+1 at the API level | Batch endpoint or single query |
| Images without `next/image` | No lazy loading, no optimization | Always use `next/image` |
| No code splitting | Monolithic bundle | `dynamic()` for heavy routes |

### Database Anti-Patterns

| Anti-Pattern | Why It's Bad | Fix |
|-------------|--------------|-----|
| Composite index `(company_id, workspace_id, domain_id)` | Wastes space, wrong query pattern | Separate indexes per level |
| No index on `domain_id` | Every hot-path query is a seq scan | Always index `domain_id` |
| `OFFSET` on large tables | Scans and discards rows | Cursor-based pagination |
| No `WHERE` on `deleted_at` index | Index includes soft-deleted rows | Partial index: `WHERE deleted_at IS NULL` |
| Missing vacuum tuning | Table bloat, slow scans | Tune autovacuum per table |
| TimescaleDB without compression | Storage cost grows linearly | Enable compression on old chunks |
| No retention policy | Infinite data growth | `add_retention_policy()` |
| `COUNT(*)` without cache | Full table scan every time | Cache count in Redis |

---

## SCALE PLANNING — KNOW YOUR NUMBERS

### Current Scale (Reference)

| Metric | Value | Notes |
|--------|-------|-------|
| Largest customer | 50,000 recipients | Across 4 workspaces, 5 domains |
| Largest single workspace | 35,000 records | Hot path — must be fast |
| Domains per workspace | 1-3 typical | Up to 5 for largest customer |
| Workspaces per company | 1-4 typical | Up to 4 for largest customer |
| Concurrent API users | ~50-200 | Peak during business hours |

### Scaling Thresholds

| Records per Domain | Action Required |
|-------------------|-----------------|
| < 10,000 | No optimization needed — defaults work |
| 10,000 - 50,000 | Ensure proper indexes, cursor pagination, Redis caching |
| 50,000 - 200,000 | Connection pooling, query optimization, table partitioning evaluation |
| 200,000 - 1,000,000 | Read replicas, aggressive caching, materialized views |
| > 1,000,000 | Sharding evaluation, dedicated infrastructure per tenant tier |

### Load Testing Checklist

Before claiming performance is acceptable:

- [ ] Load test with realistic data volume (not 100 rows)
- [ ] Test with largest customer's data shape (35K records, 5 domains)
- [ ] Test concurrent requests (not just sequential)
- [ ] Test with cold cache (Redis flushed)
- [ ] Test with warm cache (steady state)
- [ ] Measure p95 and p99, not just average
- [ ] Monitor memory during test (look for leaks)
- [ ] Monitor connection pool during test (look for exhaustion)

---

## MASTER CHECKLIST — Run Before Shipping Any Performance Work

### Measurement

- [ ] Performance budgets defined and documented
- [ ] Baseline measurements taken BEFORE optimization
- [ ] After measurements taken with same methodology
- [ ] Improvement is statistically significant (not noise)
- [ ] p95 and p99 measured, not just average/median

### Backend

- [ ] No N+1 queries (check with query logging)
- [ ] Hot-path queries use `domain_id` index
- [ ] Connection pooling configured (PgBouncer in production)
- [ ] Redis caching for read-heavy endpoints (>90% hit rate)
- [ ] BullMQ concurrency tuned per queue type
- [ ] Rate limiting is per-domain, not global
- [ ] Large result sets use cursor-based pagination
- [ ] Bulk operations are chunked with progress reporting
- [ ] No synchronous file I/O or unbounded `Promise.all`
- [ ] API response times within budget (p95 < 200ms)

### Frontend

- [ ] Bundle size within budget (main < 200KB gzip)
- [ ] No full-library imports (lodash, icons, moment)
- [ ] Heavy components use `dynamic()` import
- [ ] Tables with >500 rows are virtualized
- [ ] TanStack Query has appropriate `staleTime`
- [ ] Images use `next/image` with proper sizing
- [ ] Lighthouse scores: Performance > 90, LCP < 2s
- [ ] React Profiler shows no unnecessary re-renders on critical paths

### Database

- [ ] Every table queried by `domain_id` has an index on it
- [ ] Soft-delete tables use partial index `WHERE deleted_at IS NULL`
- [ ] `pg_stat_statements` enabled and monitored
- [ ] No sequential scans on tables with >1K rows (check EXPLAIN)
- [ ] TimescaleDB hypertables have compression + retention policies
- [ ] Autovacuum tuned for high-update tables
- [ ] Connection pool sized correctly (formula applied)

### Monitoring

- [ ] Slow query logging enabled (>50ms threshold)
- [ ] API timing middleware deployed
- [ ] Redis cache hit ratio monitored
- [ ] BullMQ dashboard accessible
- [ ] Memory usage tracked per service
- [ ] Alerts configured for budget violations

---

## REFERENCE FILES

| File | Contents |
|------|----------|
| `backend-perf.md` | N+1 detection, Redis caching patterns, BullMQ tuning, connection pooling, bulk operations |
| `frontend-perf.md` | Bundle analysis, React profiling, virtualization, lazy loading, TanStack Query, Lighthouse CI |
| `database-perf.md` | EXPLAIN ANALYZE guide, index strategy, TimescaleDB tuning, pg_stat_statements, vacuum, partitioning |
