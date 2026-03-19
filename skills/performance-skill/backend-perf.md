# Backend Performance — N+1 Detection, Caching, BullMQ, Connection Pooling

> Read this file when optimizing API response times, fixing N+1 queries, configuring
> Redis caching, tuning BullMQ job queues, or sizing connection pools.

---

## Table of Contents

1. [N+1 Detection and Fix Patterns](#n1-detection-and-fix-patterns)
2. [Redis Caching Patterns](#redis-caching-patterns)
3. [BullMQ Tuning](#bullmq-tuning)
4. [Connection Pool Sizing](#connection-pool-sizing)
5. [API Response Time Optimization](#api-response-time-optimization)
6. [Bulk Operation Optimization](#bulk-operation-optimization)
7. [Memory Management](#memory-management)

---

## N+1 Detection and Fix Patterns

### How to Detect N+1 Queries

**Method 1: Query logging count**

```typescript
// Add to development setup — counts queries per request
let queryCount = 0;

prisma.$on('query', () => { queryCount++; });

app.use((req, res, next) => {
  queryCount = 0;
  res.on('finish', () => {
    if (queryCount > 10) {
      console.warn(`N+1 ALERT: ${req.method} ${req.path} — ${queryCount} queries`);
    }
  });
  next();
});
```

**Method 2: pg_stat_statements (production)**

```sql
-- Find queries with suspiciously high call counts
SELECT
  query,
  calls,
  mean_exec_time,
  total_exec_time
FROM pg_stat_statements
WHERE calls > 1000
  AND query NOT LIKE '%pg_%'
ORDER BY calls DESC
LIMIT 20;

-- If you see a simple SELECT with 10,000+ calls and mean_exec_time < 1ms,
-- that is almost certainly an N+1 being called in a loop.
```

**Method 3: Log pattern matching**

```
# Look for repeated queries with different IDs in quick succession.
# If you see this pattern in logs, it is N+1:
SELECT * FROM tags WHERE recipient_id = 'aaa'   -- 0.5ms
SELECT * FROM tags WHERE recipient_id = 'bbb'   -- 0.4ms
SELECT * FROM tags WHERE recipient_id = 'ccc'   -- 0.6ms
... x 1000
```

### Prisma N+1 Fixes

```typescript
// BAD: N+1 — one query per recipient
const recipients = await prisma.recipient.findMany({
  where: { domainId },
});
for (const r of recipients) {
  const tags = await prisma.tag.findMany({
    where: { recipientId: r.id },
  }); // This runs N times!
  r.tags = tags;
}

// GOOD: Single query with JOIN (Prisma include)
const recipients = await prisma.recipient.findMany({
  where: { domainId },
  include: {
    tags: true, // Prisma generates a single JOIN query
  },
});

// GOOD: Select only needed fields
const recipients = await prisma.recipient.findMany({
  where: { domainId },
  select: {
    id: true,
    email: true,
    firstName: true,
    tags: {
      select: {
        id: true,
        name: true,
      },
    },
  },
});

// GOOD: Batch lookup when include is not available
const recipients = await prisma.recipient.findMany({
  where: { domainId },
});
const recipientIds = recipients.map((r) => r.id);
const allTags = await prisma.tag.findMany({
  where: { recipientId: { in: recipientIds } }, // 1 query, not N
});
const tagsByRecipient = groupBy(allTags, 'recipientId');
const enriched = recipients.map((r) => ({
  ...r,
  tags: tagsByRecipient[r.id] ?? [],
}));
```

### Drizzle N+1 Fixes

```typescript
// BAD: N+1 with Drizzle
const allRecipients = await db
  .select()
  .from(recipients)
  .where(eq(recipients.domainId, domainId));

for (const r of allRecipients) {
  const recipientTags = await db
    .select()
    .from(tags)
    .where(eq(tags.recipientId, r.id)); // N queries!
}

// GOOD: LEFT JOIN
const result = await db
  .select({
    recipient: recipients,
    tag: tags,
  })
  .from(recipients)
  .leftJoin(tags, eq(recipients.id, tags.recipientId))
  .where(eq(recipients.domainId, domainId));

// GOOD: Batch with inArray
const allRecipients = await db
  .select()
  .from(recipients)
  .where(eq(recipients.domainId, domainId));

const recipientIds = allRecipients.map((r) => r.id);
const allTags = await db
  .select()
  .from(tags)
  .where(inArray(tags.recipientId, recipientIds)); // 1 query

// GOOD: Drizzle relational query (if relations defined)
const result = await db.query.recipients.findMany({
  where: eq(recipients.domainId, domainId),
  with: {
    tags: true,
  },
});
```

### Common N+1 Hotspots in Multi-Tenant SaaS

| Hotspot | N+1 Pattern | Fix |
|---------|-------------|-----|
| Recipient list with tags | Loop over recipients, fetch tags each | `include: { tags: true }` or batch `inArray` |
| Recipient list with custom fields | Loop over recipients, fetch field defs | Cache field defs per workspace in Redis |
| Campaign with recipients | Loop over campaign, fetch recipient details | JOIN or batch lookup |
| Dashboard stats per domain | Loop over domains, count recipients each | Single GROUP BY query or cached counts |
| Workspace settings per domain | Loop over domains, fetch workspace settings | Cache workspace settings, resolve once |

---

## Redis Caching Patterns

### Cache-Aside (Lazy Loading)

The default pattern. Data is loaded into cache only when requested.

```typescript
@Injectable()
export class RecipientCacheService {
  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  // Cache-aside: check cache, miss, query DB, populate cache, return
  async getRecipientCount(domainId: string): Promise<number> {
    const cacheKey = `domain:${domainId}:recipients:count`;
    const cached = await this.redis.get(cacheKey);

    if (cached !== null) {
      return parseInt(cached, 10);
    }

    const count = await this.recipientRepo.countByDomain(domainId);
    await this.redis.set(cacheKey, count.toString(), 'EX', 300); // 5min TTL
    return count;
  }

  // Invalidate on mutation
  async onRecipientCreated(domainId: string): Promise<void> {
    const pipeline = this.redis.pipeline();
    pipeline.del(`domain:${domainId}:recipients:count`);
    await pipeline.exec();
  }
}
```

### Cache-Aside with Stale-While-Revalidate

For data that can tolerate brief staleness (dashboards, counts, stats):

```typescript
async getRecipientCountSWR(domainId: string): Promise<number> {
  const cacheKey = `domain:${domainId}:recipients:count`;
  const cached = await this.redis.get(cacheKey);
  const ttl = await this.redis.ttl(cacheKey);

  // Return cached value immediately
  if (cached !== null) {
    // If TTL is low, trigger async refresh (do not await)
    if (ttl < 60) {
      this.refreshCount(domainId).catch((err) =>
        this.logger.error(`SWR refresh failed: ${err.message}`),
      );
    }
    return parseInt(cached, 10);
  }

  // Cache miss — synchronous fetch
  return this.refreshCount(domainId);
}

private async refreshCount(domainId: string): Promise<number> {
  const count = await this.recipientRepo.countByDomain(domainId);
  await this.redis.set(
    `domain:${domainId}:recipients:count`,
    count.toString(),
    'EX', 300,
  );
  return count;
}
```

### Cache Key Conventions

```
# Tenant context (resolved on every request)
domain:{domainId}:context                        -> TenantContext object (1hr TTL)

# Counts (invalidated on CUD)
domain:{domainId}:recipients:count               -> integer (5min TTL)
domain:{domainId}:{entity}:count                 -> integer (5min TTL)

# Filter results (invalidated on CUD)
domain:{domainId}:recipients:filter:{hash}       -> paginated result (5min TTL)

# Configuration (invalidated on settings change)
workspace:{workspaceId}:custom_field_defs        -> field definitions (1hr TTL)
workspace:{workspaceId}:settings                 -> workspace settings (1hr TTL)

# Billing (invalidated on subscription change)
company:{companyId}:usage:{yyyy-mm}              -> usage counters (no TTL, explicit invalidation)
company:{companyId}:subscription                 -> plan details (5min TTL)

# Job progress (auto-expires)
job:{jobId}:progress                             -> { processed, total, errors } (1hr TTL)
active_job:{domainId}:{jobName}                  -> dedup marker (1hr TTL)
```

### Cache Invalidation Patterns

```typescript
// Pattern 1: Direct invalidation on mutation
@Injectable()
export class RecipientService {
  async create(dto: CreateRecipientDto, ctx: TenantContext) {
    const recipient = await this.repo.create(dto);

    // Invalidate related caches
    await this.cacheService.invalidateRecipientCaches(ctx.domainId);

    return recipient;
  }
}

// Pattern 2: Event-driven invalidation (preferred for cross-module)
@Injectable()
export class CacheInvalidationListener {
  @OnEvent('recipient.created')
  @OnEvent('recipient.updated')
  @OnEvent('recipient.deleted')
  async handleRecipientChange(event: RecipientEvent) {
    const pipeline = this.redis.pipeline();
    pipeline.del(`domain:${event.domainId}:recipients:count`);
    // Use SCAN to find and delete filter caches (never use KEYS in production)
    const keys = await this.scanKeys(`domain:${event.domainId}:recipients:filter:*`);
    if (keys.length > 0) {
      pipeline.del(...keys);
    }
    await pipeline.exec();
  }

  @OnEvent('subscription.changed')
  async handleSubscriptionChange(event: SubscriptionEvent) {
    // Clear tenant context for ALL domains in the company
    const domains = await this.domainRepo.findByCompany(event.companyId);
    const pipeline = this.redis.pipeline();
    for (const domain of domains) {
      pipeline.del(`domain:${domain.id}:context`);
    }
    await pipeline.exec();
  }

  private async scanKeys(pattern: string): Promise<string[]> {
    const keys: string[] = [];
    let cursor = '0';
    do {
      const [nextCursor, batch] = await this.redis.scan(
        cursor, 'MATCH', pattern, 'COUNT', 100,
      );
      cursor = nextCursor;
      keys.push(...batch);
    } while (cursor !== '0');
    return keys;
  }
}
```

### Cache Warming on Deploy

```typescript
// Run after deployment — warm critical caches
@Injectable()
export class CacheWarmupService {
  async warmOnDeploy(): Promise<void> {
    const activeDomains = await this.domainRepo.findAllActive();
    const batchSize = 50;

    for (let i = 0; i < activeDomains.length; i += batchSize) {
      const batch = activeDomains.slice(i, i + batchSize);
      await Promise.all(
        batch.map(async (domain) => {
          const context = await this.buildTenantContext(domain);
          await this.redis.set(
            `domain:${domain.id}:context`,
            JSON.stringify(context),
            'EX', 3600,
          );
        }),
      );
    }

    this.logger.log(`Warmed cache for ${activeDomains.length} domains`);
  }
}
```

---

## BullMQ Tuning

### Queue Configuration

```typescript
// queue.config.ts
export const queueConfigs = {
  'email-send': {
    concurrency: 5,
    limiter: { max: 100, duration: 1000 }, // 100/sec global
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: 'exponential', delay: 1000 },
      removeOnComplete: { age: 86400 }, // 24hr
      removeOnFail: { age: 604800 },    // 7 days
    },
  },
  'bulk-import': {
    concurrency: 2, // Memory-intensive — keep low
    defaultJobOptions: {
      attempts: 2,
      backoff: { type: 'fixed', delay: 5000 },
      removeOnComplete: { age: 86400 },
      removeOnFail: { age: 604800 },
      timeout: 600000, // 10min max
    },
  },
  'bulk-update': {
    concurrency: 3,
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: 'exponential', delay: 2000 },
      removeOnComplete: { age: 86400 },
      removeOnFail: { age: 604800 },
    },
  },
  'report-generation': {
    concurrency: 1, // Sequential — heavy DB queries
    defaultJobOptions: {
      attempts: 2,
      backoff: { type: 'fixed', delay: 10000 },
      removeOnComplete: { age: 86400 },
      removeOnFail: { age: 604800 },
      timeout: 300000, // 5min max
    },
  },
};
```

### Per-Domain Rate Limiting

Global rate limits let one tenant monopolize the queue. Always rate-limit per domain.

```typescript
@Processor('email-send')
export class EmailSendProcessor extends BaseProcessor {
  async process(job: Job<EmailSendData>): Promise<void> {
    const { domainId, recipients, template } = job.data;

    // Per-domain rate limiter using Redis
    const rateLimitKey = `ratelimit:email:${domainId}`;
    const currentRate = await this.redis.incr(rateLimitKey);

    if (currentRate === 1) {
      await this.redis.expire(rateLimitKey, 1); // 1-second window
    }

    if (currentRate > 50) { // 50 emails/sec per domain
      // Re-queue with delay instead of failing
      await job.moveToDelayed(Date.now() + 1000);
      return;
    }

    await this.emailService.send(domainId, recipients, template);
  }
}
```

### Batch Processing Pattern

```typescript
@Processor('bulk-import')
export class BulkImportProcessor extends BaseProcessor {
  private readonly BATCH_SIZE = 500;

  async process(job: Job<BulkImportData>): Promise<void> {
    const { domainId, rows, tenantContext } = job.data;
    const totalRows = rows.length;
    let processed = 0;
    let errors = 0;

    for (let i = 0; i < totalRows; i += this.BATCH_SIZE) {
      const batch = rows.slice(i, i + this.BATCH_SIZE);

      try {
        const result = await this.recipientRepo.bulkInsert(domainId, batch);
        processed += result.inserted;
        errors += result.errors;
      } catch (err) {
        errors += batch.length;
        this.logger.error(`Batch ${i}-${i + this.BATCH_SIZE} failed: ${err.message}`);
      }

      // Update progress for SSE
      await this.updateProgress(job.id, {
        processed,
        total: totalRows,
        errors,
        percent: Math.round((processed / totalRows) * 100),
      });

      // Checkpoint — if the job restarts, it can resume from here
      await job.updateProgress({ lastBatchIndex: i + this.BATCH_SIZE });
    }
  }

  private async updateProgress(jobId: string, progress: JobProgress): Promise<void> {
    await this.redis.set(
      `job:${jobId}:progress`,
      JSON.stringify(progress),
      'EX', 3600,
    );
  }
}
```

### Job Deduplication

Prevent duplicate jobs for the same operation on the same domain:

```typescript
async enqueueBulkUpdate(domainId: string, filter: object): Promise<string> {
  const jobId = `bulk-update:${domainId}:${hashObject(filter)}`;

  // Check if job already exists and is active
  const existing = await this.queue.getJob(jobId);
  if (existing) {
    const state = await existing.getState();
    if (['waiting', 'active', 'delayed'].includes(state)) {
      return existing.id; // Return existing job ID, do not duplicate
    }
  }

  const job = await this.queue.add('bulk-update', {
    domainId,
    filter,
  }, {
    jobId, // BullMQ dedup: same jobId = ignored if job exists
  });

  return job.id;
}
```

### Queue Health Monitoring

```typescript
@Injectable()
export class QueueHealthService {
  async getQueueHealth(queueName: string): Promise<QueueHealth> {
    const queue = this.queues.get(queueName);
    const [waiting, active, completed, failed, delayed] = await Promise.all([
      queue.getWaitingCount(),
      queue.getActiveCount(),
      queue.getCompletedCount(),
      queue.getFailedCount(),
      queue.getDelayedCount(),
    ]);

    return {
      name: queueName,
      waiting,
      active,
      completed,
      failed,
      delayed,
      isHealthy: waiting < 1000 && failed < 100,
      isBacklogged: waiting > 500,
    };
  }
}
```

---

## Connection Pool Sizing

### Formula

```
optimal_pool_size = (core_count * 2) + effective_spindle_count
```

For cloud instances with SSDs (no physical spindles):

```
optimal_pool_size = (core_count * 2) + 1
```

### Architecture: App to PgBouncer to PostgreSQL

```
+------------------+     +--------------+     +--------------+
|  NestJS App      |     |  PgBouncer   |     |  PostgreSQL  |
|  Pool: 20 conns  |---->|  Pool: 10    |---->|  max: 100    |
|  (per instance)  |     |  (per db)    |     |              |
+------------------+     +--------------+     +--------------+
         x 3 instances          x 1                  x 1
     = 60 app conns         = 10 PG conns       100 max
```

**Rules:**
- App-level pool (Prisma/Drizzle) connects to PgBouncer, not directly to PostgreSQL
- PgBouncer `default_pool_size` = result of the formula
- App pool size = 2-3x PgBouncer pool (connections queue in PgBouncer)
- PostgreSQL `max_connections` > (PgBouncer pool x number of databases) + 10 reserved

### PgBouncer Configuration

```ini
; pgbouncer.ini
[databases]
myapp = host=localhost port=5432 dbname=myapp

[pgbouncer]
listen_port = 6432
listen_addr = 0.0.0.0

; Pool mode: transaction is best for web workloads
; - transaction: connection returned after each transaction (recommended)
; - session: connection held for entire client session (needed for LISTEN/NOTIFY)
pool_mode = transaction

; Pool sizing
default_pool_size = 10          ; connections per user/database pair
min_pool_size = 2               ; pre-warm this many connections
reserve_pool_size = 5           ; extra connections for burst
reserve_pool_timeout = 3        ; seconds to wait before using reserve

; Limits
max_client_conn = 200           ; max client connections to PgBouncer
max_db_connections = 50         ; max connections to a single database

; Timeouts
server_idle_timeout = 600       ; close idle server connections after 10min
client_idle_timeout = 0         ; do not close idle client connections
query_timeout = 30              ; kill queries running longer than 30s
query_wait_timeout = 120        ; max time a query waits for a connection

; Logging
log_connections = 0
log_disconnections = 0
log_pooler_errors = 1
stats_period = 60
```

### Prisma Connection Configuration

```typescript
// When connecting through PgBouncer
const prisma = new PrismaClient({
  datasources: {
    db: {
      url: process.env.DATABASE_URL, // points to PgBouncer port 6432
      // Add ?pgbouncer=true&connection_limit=20 to the URL
    },
  },
});
```

### Drizzle Connection Configuration

```typescript
import { Pool } from 'pg';
import { drizzle } from 'drizzle-orm/node-postgres';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL, // points to PgBouncer
  max: 20,                    // app-level pool size
  min: 2,                     // keep 2 connections warm
  idleTimeoutMillis: 30000,   // close idle connections after 30s
  connectionTimeoutMillis: 5000, // fail if cannot connect in 5s
});

const db = drizzle(pool);
```

---

## API Response Time Optimization

### Layered Timing

Add timing to each layer to identify where time is spent:

```typescript
// repository layer — measure DB time
async findByDomain(domainId: string, opts: PaginationOpts) {
  const start = process.hrtime.bigint();
  const result = await db.select()
    .from(recipients)
    .where(eq(recipients.domainId, domainId))
    .limit(opts.limit)
    .offset(opts.offset);
  const duration = Number(process.hrtime.bigint() - start) / 1_000_000;

  if (duration > 50) {
    this.logger.warn(`Slow query in findByDomain: ${duration.toFixed(1)}ms`);
  }
  return result;
}
```

### Slow Endpoint Detection

```typescript
// Create a decorator for automatic endpoint timing
function Timed(threshold = 200) {
  return function (target: any, key: string, descriptor: PropertyDescriptor) {
    const original = descriptor.value;
    descriptor.value = async function (...args: any[]) {
      const start = process.hrtime.bigint();
      try {
        return await original.apply(this, args);
      } finally {
        const duration = Number(process.hrtime.bigint() - start) / 1_000_000;
        if (duration > threshold) {
          Logger.warn(
            `SLOW: ${target.constructor.name}.${key} took ${duration.toFixed(1)}ms`,
            'Performance',
          );
        }
      }
    };
    return descriptor;
  };
}

// Usage
@Get()
@Timed(200) // warn if > 200ms
async list(@Param('domainId') domainId: string) {
  return this.service.list(domainId);
}
```

### Response Compression

```typescript
// main.ts — enable compression for API responses
import compression from 'compression';

app.use(compression({
  filter: (req, res) => {
    if (req.headers['x-no-compression']) return false;
    return compression.filter(req, res);
  },
  threshold: 1024, // only compress responses > 1KB
  level: 6,        // balanced speed vs compression ratio
}));
```

---

## Bulk Operation Optimization

### Batch INSERT

```typescript
// BAD: Insert one at a time
for (const row of rows) {
  await db.insert(recipients).values(row);
}

// GOOD: Batch insert with chunking
const CHUNK_SIZE = 500;
for (let i = 0; i < rows.length; i += CHUNK_SIZE) {
  const chunk = rows.slice(i, i + CHUNK_SIZE);
  await db.insert(recipients).values(chunk);
}

// BEST: Batch insert with ON CONFLICT for upserts
const CHUNK_SIZE = 500;
for (let i = 0; i < rows.length; i += CHUNK_SIZE) {
  const chunk = rows.slice(i, i + CHUNK_SIZE);
  await db.insert(recipients)
    .values(chunk)
    .onConflictDoUpdate({
      target: [recipients.domainId, recipients.email],
      set: {
        firstName: sql`EXCLUDED.first_name`,
        lastName: sql`EXCLUDED.last_name`,
        updatedAt: sql`NOW()`,
      },
    });
}
```

### Batch UPDATE

```typescript
// BAD: Update one at a time
for (const id of ids) {
  await db.update(recipients).set({ status: 'active' }).where(eq(recipients.id, id));
}

// GOOD: Batch update with inArray
await db
  .update(recipients)
  .set({ status: 'active', updatedAt: new Date() })
  .where(inArray(recipients.id, ids));

// For very large ID sets (>10K), chunk the inArray
const CHUNK_SIZE = 5000;
for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
  const chunk = ids.slice(i, i + CHUNK_SIZE);
  await db
    .update(recipients)
    .set({ status: 'active', updatedAt: new Date() })
    .where(inArray(recipients.id, chunk));
}
```

### Batch DELETE (Soft)

```typescript
// Soft delete in batches to avoid long-running transactions
async bulkSoftDelete(domainId: string, ids: string[]): Promise<number> {
  const CHUNK_SIZE = 5000;
  let totalDeleted = 0;

  for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
    const chunk = ids.slice(i, i + CHUNK_SIZE);
    const result = await db
      .update(recipients)
      .set({ deletedAt: new Date() })
      .where(
        and(
          eq(recipients.domainId, domainId),
          inArray(recipients.id, chunk),
          isNull(recipients.deletedAt), // idempotent
        ),
      )
      .returning({ id: recipients.id });

    totalDeleted += result.length;
  }

  return totalDeleted;
}
```

---

## Memory Management

### Streaming Large Datasets

```typescript
// BAD: Load all rows into memory for export
const allRecipients = await db.select().from(recipients)
  .where(eq(recipients.domainId, domainId));
// 50,000 rows x ~2KB each = ~100MB in memory

// GOOD: Stream with cursor
import Cursor from 'pg-cursor';

async exportRecipients(domainId: string, res: Response): Promise<void> {
  const client = await pool.connect();
  try {
    const cursor = client.query(
      new Cursor('SELECT * FROM recipients WHERE domain_id = $1', [domainId]),
    );

    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename=recipients.csv');

    const BATCH = 1000;
    let rows = await cursor.read(BATCH);

    while (rows.length > 0) {
      for (const row of rows) {
        res.write(formatCsvRow(row));
      }
      rows = await cursor.read(BATCH);
    }

    cursor.close();
    res.end();
  } finally {
    client.release();
  }
}
```

### Bounded Promise Concurrency

```typescript
import pLimit from 'p-limit';

// BAD: Unbounded — can exhaust memory and connections
await Promise.all(
  recipients.map((r) => sendEmail(r)), // 50,000 concurrent promises
);

// GOOD: Bounded concurrency
const limit = pLimit(10); // max 10 concurrent
await Promise.all(
  recipients.map((r) => limit(() => sendEmail(r))),
);

// ALSO GOOD: Chunked sequential batches
const CHUNK_SIZE = 100;
for (let i = 0; i < recipients.length; i += CHUNK_SIZE) {
  const chunk = recipients.slice(i, i + CHUNK_SIZE);
  await Promise.all(chunk.map((r) => sendEmail(r)));
}
```

### Memory Leak Detection

```typescript
// Add to NestJS bootstrap for development monitoring
if (process.env.NODE_ENV === 'development') {
  setInterval(() => {
    const usage = process.memoryUsage();
    const rss = Math.round(usage.rss / 1024 / 1024);
    const heap = Math.round(usage.heapUsed / 1024 / 1024);

    if (rss > 512) {
      console.warn(`HIGH MEMORY: RSS=${rss}MB, Heap=${heap}MB`);
    }
  }, 30000); // Check every 30s
}
```

### Event Loop Monitoring

```typescript
// Detect event loop delays that indicate blocking operations
let lastCheck = process.hrtime.bigint();

setInterval(() => {
  const now = process.hrtime.bigint();
  const delta = Number(now - lastCheck) / 1_000_000; // ms
  lastCheck = now;

  // Timer fires every 1000ms. If delta >> 1000, the event loop was blocked.
  if (delta > 1500) {
    console.warn(`EVENT LOOP BLOCKED for ${(delta - 1000).toFixed(0)}ms`);
  }
}, 1000);
```
