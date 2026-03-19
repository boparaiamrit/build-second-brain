# Database Performance — Indexing, Query Plans, TimescaleDB, Vacuum, Partitioning

> Read this file when optimizing slow queries, designing indexes for multi-tenant tables,
> configuring TimescaleDB hypertables, setting up pg_stat_statements, or tuning autovacuum.

---

## Table of Contents

1. [PostgreSQL Query Optimization](#postgresql-query-optimization)
2. [EXPLAIN ANALYZE Reading Guide](#explain-analyze-reading-guide)
3. [Index Strategy for Multi-Tenant](#index-strategy-for-multi-tenant)
4. [Index Types and When to Use Each](#index-types-and-when-to-use-each)
5. [TimescaleDB Optimization](#timescaledb-optimization)
6. [pg_stat_statements Setup and Usage](#pg_stat_statements-setup-and-usage)
7. [Connection Pooling with PgBouncer](#connection-pooling-with-pgbouncer)
8. [Vacuum and Autovacuum Tuning](#vacuum-and-autovacuum-tuning)
9. [Table Partitioning](#table-partitioning)

---

## PostgreSQL Query Optimization

### Golden Rules

1. **Every hot-path query must use an index.** No exceptions.
2. **SELECT only the columns you need.** Never `SELECT *` in production code.
3. **Filter early.** Put the most selective predicate first (though PostgreSQL's planner usually reorders).
4. **Use EXPLAIN ANALYZE before and after.** Measure, do not guess.
5. **Watch for implicit casts.** `WHERE uuid_column = '...'` is fine, but `WHERE int_column = '1'::text` prevents index usage.

### Query Pattern by Tenant Level

```sql
-- HOT PATH: CRUD operations (most queries) — filter by domain_id
SELECT id, email, first_name, last_name, status
FROM recipients
WHERE domain_id = $1          -- Uses idx_recipients_domain
  AND deleted_at IS NULL      -- Uses partial index if available
ORDER BY created_at DESC
LIMIT 50;

-- DASHBOARD: Cross-domain reporting — filter by workspace_id
SELECT domain_id, COUNT(*) as count
FROM recipients
WHERE workspace_id = $1       -- Uses idx_recipients_workspace
  AND deleted_at IS NULL
GROUP BY domain_id;

-- BILLING: Subscription enforcement — filter by company_id
SELECT COUNT(*) as total_recipients
FROM recipients
WHERE company_id = $1;        -- Uses idx_recipients_company
```

### Covering Indexes (Index-Only Scans)

A covering index contains all columns the query needs, so PostgreSQL never reads the table.

```sql
-- Query: get recipient count per status for a domain
SELECT status, COUNT(*)
FROM recipients
WHERE domain_id = $1 AND deleted_at IS NULL
GROUP BY status;

-- Covering index: includes status so the query reads only the index
CREATE INDEX idx_recipients_domain_status
ON recipients(domain_id, status)
WHERE deleted_at IS NULL;

-- Verify with EXPLAIN: look for "Index Only Scan"
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, COUNT(*)
FROM recipients
WHERE domain_id = 'abc' AND deleted_at IS NULL
GROUP BY status;
-- Should show: Index Only Scan using idx_recipients_domain_status
```

### Partial Indexes for Soft Deletes

Every table with soft deletes should have partial indexes excluding deleted rows:

```sql
-- BAD: Full index includes deleted rows (wasted space, slower scans)
CREATE INDEX idx_recipients_domain ON recipients(domain_id);

-- GOOD: Partial index — only indexes non-deleted rows
CREATE INDEX idx_recipients_domain_active
ON recipients(domain_id)
WHERE deleted_at IS NULL;

-- For unique constraints with soft deletes
CREATE UNIQUE INDEX uq_recipients_domain_email_active
ON recipients(domain_id, email)
WHERE deleted_at IS NULL;
-- Allows re-creating a recipient with the same email after soft delete
```

### Count Optimization

```sql
-- BAD: COUNT(*) on large table — full index scan every time
SELECT COUNT(*) FROM recipients WHERE domain_id = $1;
-- For 35K rows: ~10-50ms depending on cache state

-- GOOD: Cached count in Redis (see backend-perf.md)
-- Only run COUNT on cache miss, store result with 5min TTL

-- GOOD: Approximate count when exact number is not needed
SELECT reltuples::bigint AS estimate
FROM pg_class
WHERE relname = 'recipients';
-- Instant, but only accurate after ANALYZE

-- GOOD: Use window function to get total with paginated data
SELECT *, COUNT(*) OVER() as total_count
FROM recipients
WHERE domain_id = $1 AND deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 50 OFFSET 0;
-- Warning: window function COUNT still scans all matching rows.
-- For very large tables (>100K rows), prefer cached count.
```

---

## EXPLAIN ANALYZE Reading Guide

### How to Run

```sql
-- Always use ANALYZE + BUFFERS for real execution stats
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM recipients
WHERE domain_id = 'abc-123'
  AND status = 'active'
  AND deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 50;
```

### Reading the Output

```
Limit  (cost=0.42..15.30 rows=50 width=312) (actual time=0.031..0.145 rows=50 loops=1)
  ->  Index Scan Backward using idx_recipients_domain_created
        on recipients  (cost=0.42..892.15 rows=3000 width=312)
        (actual time=0.029..0.138 rows=50 loops=1)
        Index Cond: (domain_id = 'abc-123'::uuid)
        Filter: ((deleted_at IS NULL) AND (status = 'active'::text))
        Rows Removed by Filter: 5
        Buffers: shared hit=12
Planning Time: 0.185 ms
Execution Time: 0.172 ms
```

**What each part means:**

| Field | Meaning | What to Check |
|-------|---------|---------------|
| `cost=0.42..15.30` | Estimated startup..total cost (arbitrary units) | High cost = expensive query |
| `rows=50` | Estimated rows returned | Compare estimate to actual |
| `actual time=0.031..0.145` | Real startup..total time in ms | Is it within budget? |
| `rows=50 loops=1` | Actual rows returned, number of times executed | `loops > 1` in nested loops = potential problem |
| `Index Scan` | Using an index | Good |
| `Seq Scan` | Full table scan | Bad on large tables |
| `Filter` | Post-index filtering | Rows removed by filter = wasted reads |
| `Buffers: shared hit=12` | Pages read from cache | `shared read` = disk I/O (cold cache) |

### Red Flags in EXPLAIN Output

| Red Flag | What It Means | Fix |
|----------|---------------|-----|
| `Seq Scan` on table > 1K rows | No usable index | Create appropriate index |
| `Rows Removed by Filter: 10000` | Index is too broad, post-filtering too many rows | More selective index or composite index |
| `Sort` without `Index Scan` | Sorting in memory, not from index | Index on sort column or composite index |
| `Nested Loop` with `actual loops=5000` | N+1 at the database level | Rewrite as JOIN or use `inArray` |
| `Hash Join` with large `Batches: 4` | Hash table spilled to disk | Increase `work_mem` or reduce result set |
| `Buffers: shared read=500` (high) | Data not in PostgreSQL buffer cache | Run query again to confirm (first run is cold) |
| Estimated rows differ wildly from actual | Stale statistics | Run `ANALYZE table_name;` |
| `Planning Time` > `Execution Time` | Query is very simple but plan is complex | Simplify query or reduce indexes |

### Common Query Plan Improvements

```sql
-- BEFORE: Seq Scan + Sort (bad for large tables)
-- Cost: 1500.00  Time: 45ms
EXPLAIN ANALYZE
SELECT * FROM recipients
WHERE domain_id = 'abc' AND status = 'active'
ORDER BY created_at DESC
LIMIT 50;

-- FIX: Composite index matching the query pattern
CREATE INDEX idx_recipients_domain_status_created
ON recipients(domain_id, status, created_at DESC)
WHERE deleted_at IS NULL;

-- AFTER: Index Scan (fast, no sort needed)
-- Cost: 15.00  Time: 0.2ms
```

---

## Index Strategy for Multi-Tenant

### Tier 1: Always Create (Hot Path)

Every table that is queried by domain_id in CRUD operations:

```sql
-- Basic domain index
CREATE INDEX idx_{table}_domain
ON {table}(domain_id)
WHERE deleted_at IS NULL;

-- If the table is frequently sorted by created_at
CREATE INDEX idx_{table}_domain_created
ON {table}(domain_id, created_at DESC)
WHERE deleted_at IS NULL;

-- If the table has a unique constraint per domain
CREATE UNIQUE INDEX uq_{table}_domain_email
ON {table}(domain_id, email)
WHERE deleted_at IS NULL;
```

### Tier 2: Add When Proven (Dashboards)

Only add these when you have a real query that filters by workspace_id:

```sql
-- Dashboard query: cross-domain stats within a workspace
CREATE INDEX idx_{table}_workspace
ON {table}(workspace_id)
WHERE deleted_at IS NULL;

-- Dashboard with grouping
CREATE INDEX idx_{table}_workspace_domain
ON {table}(workspace_id, domain_id)
WHERE deleted_at IS NULL;
```

### Tier 3: Add When Proven (Billing)

Only add these when you have a real query that filters by company_id:

```sql
-- Billing: total count across company
CREATE INDEX idx_{table}_company
ON {table}(company_id)
WHERE deleted_at IS NULL;
```

### NEVER: Composite With All Three

```sql
-- BAD: This composite index is almost never useful
-- The leftmost columns must match the query's WHERE clause.
-- If you query by domain_id alone, this index is USELESS because
-- company_id is the leftmost column.
CREATE INDEX idx_bad ON {table}(company_id, workspace_id, domain_id);
```

### Index Sizing and Monitoring

```sql
-- Check index sizes
SELECT
  schemaname || '.' || tablename AS table,
  indexname,
  pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 20;

-- Find unused indexes (candidates for removal)
SELECT
  schemaname || '.' || tablename AS table,
  indexrelname AS index,
  idx_scan AS times_used,
  pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexrelname NOT LIKE 'uq_%'    -- Keep unique constraints
  AND indexrelname NOT LIKE '%pkey%'   -- Keep primary keys
ORDER BY pg_relation_size(indexrelid) DESC;

-- Find missing indexes (tables with many seq scans)
SELECT
  schemaname || '.' || relname AS table,
  seq_scan,
  seq_tup_read,
  idx_scan,
  CASE WHEN seq_scan > 0
    THEN round(seq_tup_read::numeric / seq_scan)
    ELSE 0
  END AS avg_rows_per_seq_scan
FROM pg_stat_user_tables
WHERE seq_scan > 100
  AND seq_tup_read / GREATEST(seq_scan, 1) > 1000
ORDER BY seq_tup_read DESC
LIMIT 20;
```

---

## Index Types and When to Use Each

| Type | Use Case | Example |
|------|----------|---------|
| B-tree (default) | Equality, range, sorting | `WHERE domain_id = $1`, `ORDER BY created_at` |
| GIN | JSONB containment, array ops, full-text | `WHERE custom_fields @> '{"industry":"tech"}'` |
| GiST | Full-text search, geometric, range types | `WHERE tsv @@ to_tsquery('english', 'security')` |
| BRIN | Time-series / append-only data | `WHERE created_at > '2024-01-01'` on large tables |
| Hash | Equality-only (rare, B-tree is usually better) | Almost never needed |

### GIN Index for JSONB Custom Fields

```sql
-- Index for @> containment queries on custom_fields
CREATE INDEX idx_recipients_custom_fields
ON recipients USING GIN (custom_fields)
WHERE deleted_at IS NULL;

-- Querying custom fields
SELECT * FROM recipients
WHERE domain_id = $1
  AND custom_fields @> '{"industry": "technology"}'::jsonb
  AND deleted_at IS NULL;

-- For specific key lookups (more selective, smaller index)
CREATE INDEX idx_recipients_cf_industry
ON recipients ((custom_fields->>'industry'))
WHERE deleted_at IS NULL;
```

### BRIN Index for Time-Series Data

```sql
-- BRIN is tiny (1000x smaller than B-tree) but only works well
-- on physically ordered data (like time-series inserts)
CREATE INDEX idx_events_time_brin
ON email_events USING BRIN (time)
WITH (pages_per_range = 32);

-- BRIN is ideal for TimescaleDB hypertables where data is
-- naturally ordered by time within each chunk
```

---

## TimescaleDB Optimization

### Hypertable Setup

```sql
-- Convert a regular table to a hypertable
-- IMPORTANT: Do this before inserting data (or migrate existing data)
SELECT create_hypertable('email_events', 'time',
  chunk_time_interval => INTERVAL '7 days',
  migrate_data => true  -- if table already has data
);
```

### Chunk Interval Tuning

The chunk interval determines how much data is in each chunk. The goal: each chunk should fit ~25% of available memory.

```sql
-- Check current chunk sizes
SELECT
  hypertable_name,
  chunk_name,
  range_start,
  range_end,
  pg_size_pretty(total_bytes) AS size
FROM timescaledb_information.chunks
WHERE hypertable_name = 'email_events'
ORDER BY range_start DESC
LIMIT 10;

-- If chunks are too large (>1GB each), reduce the interval
SELECT set_chunk_time_interval('email_events', INTERVAL '3 days');

-- If chunks are too small (<50MB each), increase the interval
SELECT set_chunk_time_interval('email_events', INTERVAL '14 days');
```

**Guidelines:**

| Daily Insert Volume | Recommended Chunk Interval |
|--------------------|-----------------------------|
| < 100K rows/day | 14 days |
| 100K - 1M rows/day | 7 days (default) |
| 1M - 10M rows/day | 3 days |
| > 10M rows/day | 1 day |

### Retention Policies

```sql
-- Automatically drop chunks older than 90 days
SELECT add_retention_policy('email_events', INTERVAL '90 days');

-- Verify retention policy
SELECT * FROM timescaledb_information.jobs
WHERE proc_name = 'policy_retention';

-- Manual cleanup (if needed)
SELECT drop_chunks('email_events', older_than => INTERVAL '90 days');
```

### Compression

```sql
-- Enable compression on the hypertable
ALTER TABLE email_events SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'domain_id',  -- queries filter by domain
  timescaledb.compress_orderby = 'time DESC'       -- queries order by time
);

-- Automatically compress chunks older than 7 days
SELECT add_compression_policy('email_events', INTERVAL '7 days');

-- Check compression stats
SELECT
  hypertable_name,
  chunk_name,
  pg_size_pretty(before_compression_total_bytes) AS before,
  pg_size_pretty(after_compression_total_bytes) AS after,
  round(
    (1 - after_compression_total_bytes::numeric / before_compression_total_bytes) * 100,
    1
  ) AS compression_pct
FROM timescaledb_information.compressed_chunk_stats
WHERE hypertable_name = 'email_events'
ORDER BY chunk_name DESC
LIMIT 10;

-- Typical compression ratio: 90-95% for event data
```

### Continuous Aggregates

Pre-compute rollups for dashboard queries instead of scanning raw data:

```sql
-- Hourly aggregates for email events
CREATE MATERIALIZED VIEW email_events_hourly
WITH (timescaledb.continuous) AS
SELECT
  domain_id,
  time_bucket('1 hour', time) AS bucket,
  event_type,
  COUNT(*) AS event_count,
  COUNT(DISTINCT recipient_id) AS unique_recipients
FROM email_events
GROUP BY domain_id, time_bucket('1 hour', time), event_type
WITH NO DATA;

-- Refresh policy: update every hour, cover last 3 hours
SELECT add_continuous_aggregate_policy('email_events_hourly',
  start_offset => INTERVAL '3 hours',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour'
);

-- Daily aggregates (built on top of hourly for efficiency)
CREATE MATERIALIZED VIEW email_events_daily
WITH (timescaledb.continuous) AS
SELECT
  domain_id,
  time_bucket('1 day', bucket) AS day,
  event_type,
  SUM(event_count) AS event_count,
  SUM(unique_recipients) AS unique_recipients
FROM email_events_hourly
GROUP BY domain_id, time_bucket('1 day', bucket), event_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('email_events_daily',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day'
);

-- Query the aggregate instead of raw table
-- BEFORE: scans millions of raw events
SELECT
  date_trunc('day', time) AS day,
  event_type,
  COUNT(*)
FROM email_events
WHERE domain_id = $1
  AND time > NOW() - INTERVAL '30 days'
GROUP BY 1, 2;

-- AFTER: reads pre-computed daily rollup (instant)
SELECT day, event_type, event_count
FROM email_events_daily
WHERE domain_id = $1
  AND day > NOW() - INTERVAL '30 days';
```

---

## pg_stat_statements Setup and Usage

### Installation

```sql
-- Enable the extension (requires superuser)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Verify
SELECT * FROM pg_stat_statements LIMIT 1;
```

Add to `postgresql.conf`:

```ini
shared_preload_libraries = 'pg_stat_statements,timescaledb'
pg_stat_statements.max = 10000      # max tracked queries
pg_stat_statements.track = 'all'    # track all statements
pg_stat_statements.track_utility = on
```

### Finding Slow Queries

```sql
-- Top 20 queries by total time (most impact on overall performance)
SELECT
  queryid,
  LEFT(query, 100) AS query_preview,
  calls,
  round(total_exec_time::numeric, 2) AS total_time_ms,
  round(mean_exec_time::numeric, 2) AS avg_time_ms,
  round(max_exec_time::numeric, 2) AS max_time_ms,
  rows
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat%'
ORDER BY total_exec_time DESC
LIMIT 20;
```

### Finding N+1 Queries

```sql
-- Queries with very high call count but low avg time = N+1 candidates
SELECT
  queryid,
  LEFT(query, 120) AS query_preview,
  calls,
  round(mean_exec_time::numeric, 3) AS avg_ms,
  round(total_exec_time::numeric, 2) AS total_ms
FROM pg_stat_statements
WHERE calls > 5000
  AND mean_exec_time < 1  -- each call is fast
  AND query NOT LIKE '%pg_%'
ORDER BY calls DESC
LIMIT 20;
```

### Finding Queries Needing Indexes

```sql
-- Queries with high avg time (likely missing indexes)
SELECT
  queryid,
  LEFT(query, 120) AS query_preview,
  calls,
  round(mean_exec_time::numeric, 2) AS avg_ms,
  round((shared_blks_read::numeric / GREATEST(calls, 1)), 2) AS avg_blocks_read
FROM pg_stat_statements
WHERE mean_exec_time > 50   -- > 50ms average
  AND calls > 10            -- called more than 10 times
  AND query NOT LIKE '%pg_%'
ORDER BY mean_exec_time DESC
LIMIT 20;
```

### Resetting Statistics

```sql
-- Reset all stats (do this after a deploy to get fresh baseline)
SELECT pg_stat_statements_reset();
```

---

## Connection Pooling with PgBouncer

### Why PgBouncer

Each PostgreSQL connection consumes ~10MB RAM. With 3 app instances x 20 connections = 60 connections = 600MB just for connections. PgBouncer multiplexes these into 10-20 actual PostgreSQL connections.

### Pool Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| `transaction` | Connection released after each transaction | Default for web apps. Best performance. |
| `session` | Connection held for entire client session | Need LISTEN/NOTIFY, prepared statements, or SET commands |
| `statement` | Connection released after each statement | Rarely used. Cannot use multi-statement transactions. |

**Use `transaction` mode unless you specifically need session features.**

### Monitoring PgBouncer

```sql
-- Connect to PgBouncer admin console
-- psql -h localhost -p 6432 -U admin pgbouncer

-- Show pool stats
SHOW POOLS;
-- Look for: cl_waiting > 0 means clients are waiting for connections

-- Show active server connections
SHOW SERVERS;

-- Show client connections
SHOW CLIENTS;

-- Show aggregate stats
SHOW STATS;
-- Key metrics:
--   avg_query_time: should be < 50ms
--   avg_wait_time: should be < 10ms (time waiting for a connection)
```

### Connection Pool Health Checks

```typescript
// NestJS health check for connection pool
@Injectable()
export class DatabaseHealthIndicator extends HealthIndicator {
  async isHealthy(): Promise<HealthIndicatorResult> {
    const poolStats = await pool.query(`
      SELECT
        numbackends as active,
        (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max
      FROM pg_stat_database
      WHERE datname = current_database()
    `);

    const { active, max } = poolStats.rows[0];
    const usage = active / max;

    if (usage > 0.8) {
      return this.getStatus('database', false, {
        message: `Connection pool at ${Math.round(usage * 100)}% capacity`,
        active,
        max,
      });
    }

    return this.getStatus('database', true, { active, max });
  }
}
```

---

## Vacuum and Autovacuum Tuning

### Why Vacuum Matters

PostgreSQL uses MVCC: UPDATE and DELETE create dead tuples. VACUUM reclaims space from dead tuples. Without it, tables grow indefinitely and queries slow down.

### Autovacuum Default Behavior

```
Trigger: when dead tuples > (autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor * table_rows)
Default: 50 + 0.2 * table_rows
For 35,000 rows: triggers at 7,050 dead tuples (~20% of table)
```

For high-update tables (like recipients with frequent status changes), 20% is too much.

### Per-Table Tuning

```sql
-- For high-update tables: vacuum more aggressively
ALTER TABLE recipients SET (
  autovacuum_vacuum_threshold = 100,         -- trigger after 100 dead tuples
  autovacuum_vacuum_scale_factor = 0.05,     -- or 5% of table (not 20%)
  autovacuum_analyze_threshold = 50,         -- update statistics sooner
  autovacuum_analyze_scale_factor = 0.02     -- or 2% of table
);

-- For append-only tables (events): vacuum less often
ALTER TABLE email_events SET (
  autovacuum_vacuum_threshold = 10000,
  autovacuum_vacuum_scale_factor = 0.1
);
-- Events rarely get updated/deleted, so fewer dead tuples
```

### Monitoring Table Bloat

```sql
-- Check dead tuple count per table
SELECT
  schemaname || '.' || relname AS table,
  n_live_tup AS live_rows,
  n_dead_tup AS dead_rows,
  CASE WHEN n_live_tup > 0
    THEN round(n_dead_tup::numeric / n_live_tup * 100, 1)
    ELSE 0
  END AS dead_pct,
  last_autovacuum,
  last_autoanalyze
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC
LIMIT 20;

-- If dead_pct > 20%, autovacuum is not keeping up.
-- Either tune per-table settings or increase autovacuum_max_workers.
```

### Preventing Vacuum Issues

```sql
-- Check for long-running transactions (block vacuum)
SELECT
  pid,
  now() - xact_start AS duration,
  state,
  LEFT(query, 80) AS query
FROM pg_stat_activity
WHERE state != 'idle'
  AND xact_start < now() - INTERVAL '5 minutes'
ORDER BY xact_start;

-- Long-running transactions prevent vacuum from reclaiming space.
-- Set a statement timeout to prevent runaway queries:
ALTER DATABASE myapp SET statement_timeout = '30s';
```

---

## Table Partitioning

### When to Partition

| Condition | Partition? | Reason |
|-----------|-----------|--------|
| < 10M rows | No | Indexes are sufficient |
| 10M - 100M rows | Maybe | If queries always filter by partition key |
| > 100M rows | Yes | Query performance and maintenance benefits |
| Time-series data | Use TimescaleDB | Better than manual partitioning |
| Multi-tenant with huge tenants | Maybe | Partition by company_id if one company has >10M rows |

### Range Partitioning by Time

```sql
-- Create partitioned table
CREATE TABLE audit_logs (
  id UUID DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL,
  workspace_id UUID NOT NULL,
  domain_id UUID NOT NULL,
  action TEXT NOT NULL,
  actor_id UUID NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions
CREATE TABLE audit_logs_2024_01 PARTITION OF audit_logs
  FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE audit_logs_2024_02 PARTITION OF audit_logs
  FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
-- ... create partitions for each month

-- Automate partition creation with pg_partman
CREATE EXTENSION pg_partman;
SELECT create_parent(
  'public.audit_logs',
  'created_at',
  'native',
  'monthly'
);
-- pg_partman will auto-create future partitions
```

### List Partitioning by Tenant

For extreme cases where one company has millions of rows:

```sql
-- Partition by company_id for very large customers
CREATE TABLE recipients (
  id UUID DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL,
  workspace_id UUID NOT NULL,
  domain_id UUID NOT NULL,
  email TEXT NOT NULL,
  -- ... other columns
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY LIST (company_id);

-- Default partition for most companies
CREATE TABLE recipients_default PARTITION OF recipients DEFAULT;

-- Dedicated partition for a very large customer
CREATE TABLE recipients_large_customer PARTITION OF recipients
  FOR VALUES IN ('large-customer-uuid');

-- Each partition can have its own indexes, vacuum settings, etc.
CREATE INDEX idx_recipients_lc_domain
ON recipients_large_customer(domain_id)
WHERE deleted_at IS NULL;
```

### Partition Maintenance

```sql
-- Check partition sizes
SELECT
  parent.relname AS parent_table,
  child.relname AS partition,
  pg_size_pretty(pg_relation_size(child.oid)) AS size,
  pg_stat_get_live_tuples(child.oid) AS live_rows
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
WHERE parent.relname = 'audit_logs'
ORDER BY child.relname;

-- Detach old partitions (for archival)
ALTER TABLE audit_logs DETACH PARTITION audit_logs_2023_01;

-- Drop old partitions (for cleanup)
DROP TABLE audit_logs_2023_01;
```

### Partitioning vs. TimescaleDB

| Feature | Native Partitioning | TimescaleDB |
|---------|-------------------|-------------|
| Setup complexity | High (manual or pg_partman) | Low (one command) |
| Chunk/partition management | Manual or pg_partman | Automatic |
| Compression | Not built-in | Built-in, automatic |
| Continuous aggregates | Manual (materialized views) | Built-in, auto-refresh |
| Retention policies | Manual or pg_partman | Built-in, one command |
| Best for | Non-time-series large tables | Time-series event data |

**Rule:** If data is time-series (events, logs, metrics), use TimescaleDB. If data is not time-series but very large, use native partitioning.
