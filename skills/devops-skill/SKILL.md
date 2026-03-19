---
name: devops-skill
description: >
  Production deployment, CI/CD, Docker, monitoring, and database migration patterns for
  multi-tenant SaaS. Covers NestJS backend + Next.js frontend + PostgreSQL + TimescaleDB +
  Redis + BullMQ. Zero-downtime deployments, feature flags, rollback strategies, and
  observability. Trigger when deploying, setting up CI/CD, configuring Docker, managing
  database migrations, setting up monitoring, or planning production infrastructure.
---

# SKILL: DevOps & Production Infrastructure for Multi-Tenant SaaS

## Stack

**Backend:** NestJS + Prisma (existing) / Drizzle (new) + PostgreSQL + TimescaleDB + BullMQ + Redis
**Frontend:** Next.js 16 + React 19
**Infrastructure:** Docker + Docker Compose + GitHub Actions + Cloud-agnostic deployment
**Observability:** Pino + Sentry + OpenTelemetry + Prometheus + Grafana

---

## IDENTITY

You are a senior DevOps/platform engineer. You:

1. Design infrastructure that survives failure — every component has a health check, a fallback, and a rollback plan
2. Enforce zero-downtime deployments — no maintenance windows, no user-visible disruption
3. Treat configuration as code — no manual changes, no snowflake servers, no undocumented env vars
4. Build for observability first — if you can't see it, you can't fix it
5. Apply the principle of least privilege — containers run as non-root, secrets are injected not baked, networks are segmented

---

## CORE ARCHITECTURE — MEMORIZE THIS

### Tenant Hierarchy (Matches saas-architect-skill — Never Diverge)

```
Company (billing entity — subscriptions, plan limits, seats)
  +-- Workspace (organizational unit — settings, custom field definitions, user roles)
        +-- Domain (data partition — primary query pivot for all hot-path operations)
              +-- Data (recipients, campaigns, events — scoped per domain)
```

**Infrastructure implication:** Every service, every container, every migration must respect this hierarchy. Database migrations that break tenant isolation are production incidents, not bugs.

### Service Topology

```
                    +------------------+
                    |   Load Balancer  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     |  Next.js (SSR)  |          |  NestJS API     |
     |  Port 3000      |          |  Port 3001      |
     +-----------------+          +--------+--------+
                                           |
                        +------------------+------------------+
                        |                  |                  |
               +--------v-------+  +-------v-------+  +------v-------+
               |  PostgreSQL    |  |  Redis         |  |  BullMQ      |
               |  + TimescaleDB |  |  Port 6379     |  |  Workers     |
               |  Port 5432     |  +----------------+  +--------------+
               +----------------+
```

### Service Boundaries

| Service | Responsibility | Scaling Unit | Health Signal |
|---------|---------------|-------------|---------------|
| NestJS API | HTTP endpoints, auth, business logic | Horizontal (stateless) | `/health` endpoint |
| Next.js Frontend | SSR, static assets, client routing | Horizontal (stateless) | `/api/health` endpoint |
| BullMQ Workers | Background jobs, imports, bulk ops | Horizontal (queue-based) | Job completion rate |
| PostgreSQL + TimescaleDB | Persistent data, time-series events | Vertical (read replicas later) | Connection pool, replication lag |
| Redis | Cache, sessions, feature flags, queues | Vertical (cluster later) | Memory usage, latency |

---

## DOCKER SETUP

> Full Dockerfile templates and docker-compose configurations are in `docker.md`.

### Multi-Stage Build Strategy

Every Dockerfile follows the same three-stage pattern:

```
Stage 1: deps        — Install production dependencies only
Stage 2: build       — Install all deps, compile TypeScript, build
Stage 3: production  — Copy built artifacts + prod deps into minimal image
```

**Rules:**
- Base image: `node:22-alpine` (smallest, LTS, matches local dev)
- Never run as root in production stage — create `node` user
- Never copy `node_modules` from build to production — reinstall prod-only
- Always include `.dockerignore` — exclude `node_modules`, `.git`, `.env*`, `dist`
- Pin dependency versions in lockfile — `npm ci` not `npm install`
- Layer cache: copy `package*.json` first, then `npm ci`, then copy source

### Docker Compose Strategy

Two compose files:

| File | Purpose | Key Differences |
|------|---------|----------------|
| `docker-compose.yml` | Local development | Hot reload, source mounts, debug ports, no resource limits |
| `docker-compose.prod.yml` | Production/staging | Built images, resource limits, restart policies, no source mounts |

### Key Configuration Patterns

**PostgreSQL + TimescaleDB:**
```yaml
image: timescale/timescaledb:latest-pg16
# NOT postgres:16 — TimescaleDB extension must be pre-installed
```

**Redis persistence for local dev:**
```yaml
command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
```

**BullMQ workers — separate from API:**
```yaml
# Workers are their own service, NOT part of the API container
# Scale independently: docker compose up --scale worker=3
```

---

## ENVIRONMENT MANAGEMENT

### .env File Strategy

```
.env.example          # Committed. All keys, no values. Documentation for required vars.
.env                  # Local dev. Git-ignored. Developers copy from .env.example.
.env.test             # Test environment. Git-ignored. Used by test runner.
.env.staging          # NEVER committed. Injected via CI/CD secrets.
.env.production       # NEVER committed. Injected via CI/CD secrets.
```

**Rules:**
- Never commit real secrets. Not even "development" secrets.
- `.env.example` must list EVERY variable with a description comment.
- CI/CD environments inject secrets via GitHub Actions Secrets / cloud provider secret manager.
- Local dev uses `.env` loaded by Docker Compose `env_file` directive.

### Required Environment Variables

```bash
# === Database ===
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
# Prisma uses DATABASE_URL directly
# Drizzle uses the same connection string

# === Redis ===
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=              # Empty for local dev, required for production

# === Application ===
NODE_ENV=development         # development | test | staging | production
PORT=3001                    # NestJS API port
FRONTEND_URL=http://localhost:3000

# === Auth ===
JWT_SECRET=                  # Minimum 32 characters
JWT_EXPIRY=15m
REFRESH_TOKEN_EXPIRY=7d

# === BullMQ ===
BULL_REDIS_HOST=${REDIS_HOST}
BULL_REDIS_PORT=${REDIS_PORT}
BULL_REDIS_PASSWORD=${REDIS_PASSWORD}

# === Monitoring ===
SENTRY_DSN=                  # Empty for local dev
SENTRY_ENVIRONMENT=${NODE_ENV}
LOG_LEVEL=debug              # debug for dev, info for staging, warn for production

# === Feature Flags ===
FEATURE_FLAGS_PROVIDER=redis  # redis | unleash
UNLEASH_URL=                  # Only for production
UNLEASH_API_KEY=              # Only for production
```

### Per-Environment Configuration Pattern

```typescript
// config/configuration.ts — NestJS ConfigModule pattern
export default () => ({
  database: {
    url: process.env.DATABASE_URL,
    poolSize: process.env.NODE_ENV === 'production' ? 20 : 5,
    ssl: process.env.NODE_ENV === 'production',
  },
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
    tls: process.env.NODE_ENV === 'production' ? {} : undefined,
  },
  logging: {
    level: process.env.LOG_LEVEL || (process.env.NODE_ENV === 'production' ? 'warn' : 'debug'),
  },
  sentry: {
    dsn: process.env.SENTRY_DSN || '',
    environment: process.env.SENTRY_ENVIRONMENT || process.env.NODE_ENV,
    enabled: !!process.env.SENTRY_DSN,
  },
});
```

---

## DATABASE MIGRATION STRATEGY

### Dual ORM Migration Rules

| Context | ORM | Migration Tool | Command |
|---------|-----|---------------|---------|
| Existing tables | Prisma | `prisma migrate` | `npx prisma migrate deploy` |
| New tables | Drizzle | `drizzle-kit` | `npx drizzle-kit migrate` |
| TimescaleDB hypertables | Raw SQL | Custom migration runner | Applied after Drizzle migrations |

### Migration Execution Order (Every Deploy)

```
1. Prisma migrations (existing schema changes)
2. Drizzle migrations (new schema changes)
3. TimescaleDB setup (hypertables, retention policies, continuous aggregates)
4. Seed data (only for staging/test, never production)
```

### Zero-Downtime Migration Rules

These rules are NON-NEGOTIABLE. Violating any of them causes downtime.

| Rule | Why | Example |
|------|-----|---------|
| Additive only | Old code must work with new schema | Add column with DEFAULT, never remove |
| No renames | Old code references old name | Add new column, backfill, deprecate old |
| No type changes | Old code expects old type | Add new column with new type, migrate data |
| No NOT NULL without DEFAULT | Existing rows fail constraint | Add nullable, backfill, then add constraint |
| No DROP without feature flag | Rollback needs the column | Feature flag hides old column, drop after 2 deploys |
| No index creation on hot tables without CONCURRENTLY | Locks table | `CREATE INDEX CONCURRENTLY` (Prisma: use raw SQL migration) |

### Multi-Step Migration Pattern (Breaking Changes)

When you MUST make a breaking schema change, split it across 3 deploys:

```
Deploy 1: Add new column (nullable, with default)
  - Old code ignores new column
  - New code writes to both old and new columns

Deploy 2: Backfill + switch reads
  - Migration backfills new column from old column
  - Code reads from new column, writes to both
  - Feature flag controls which column is "source of truth"

Deploy 3: Drop old column (after verification)
  - Feature flag confirms all reads use new column
  - Migration drops old column
  - Code removes dual-write
```

### Migration CI/CD Integration

```yaml
# Migrations run as a SEPARATE step, BEFORE the application deploy
# If migration fails, the deploy is aborted — old code keeps running
migration-step:
  steps:
    - run: npx prisma migrate deploy
    - run: npx drizzle-kit migrate
    - run: node scripts/timescaledb-setup.js
```

**Rollback strategy for migrations:**
- Additive migrations (add column, add table): No rollback needed — old code ignores them
- Data migrations: Write a reverse migration script BEFORE applying
- Never rollback a destructive migration — this is why we never do destructive migrations in a single deploy

### TimescaleDB-Specific Migration

```sql
-- Always run AFTER the table is created by Drizzle
-- These are idempotent — safe to re-run

-- Create hypertable (only if not already a hypertable)
SELECT create_hypertable('email_events', 'created_at',
  chunk_time_interval => INTERVAL '7 days',
  if_not_exists => TRUE
);

-- Retention policy
SELECT add_retention_policy('email_events', INTERVAL '90 days',
  if_not_exists => TRUE
);

-- Continuous aggregate for daily rollups
CREATE MATERIALIZED VIEW IF NOT EXISTS email_events_daily
WITH (timescaledb.continuous) AS
SELECT
  domain_id,
  time_bucket('1 day', created_at) AS bucket,
  COUNT(*) AS total_events,
  COUNT(*) FILTER (WHERE event_type = 'open') AS opens,
  COUNT(*) FILTER (WHERE event_type = 'click') AS clicks
FROM email_events
GROUP BY domain_id, bucket;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('email_events_daily',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour',
  if_not_exists => TRUE
);
```

---

## FEATURE FLAGS

### Architecture

```
MVP (Local/Staging):  Redis-based feature flags (zero dependencies)
Production:           Unleash (self-hosted or managed) for gradual rollout
```

### Redis-Based Feature Flags (MVP)

```typescript
// feature-flags/feature-flag.service.ts
@Injectable()
export class FeatureFlagService {
  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  async isEnabled(flag: string, context?: { companyId?: string; workspaceId?: string }): Promise<boolean> {
    // Global kill switch
    const globalValue = await this.redis.get(`ff:${flag}`);
    if (globalValue === 'false') return false;
    if (globalValue === 'true') return true;

    // Per-company override (UC3: MSSP feature gating)
    if (context?.companyId) {
      const companyValue = await this.redis.get(`ff:${flag}:company:${context.companyId}`);
      if (companyValue !== null) return companyValue === 'true';
    }

    // Per-workspace override
    if (context?.workspaceId) {
      const wsValue = await this.redis.get(`ff:${flag}:workspace:${context.workspaceId}`);
      if (wsValue !== null) return wsValue === 'true';
    }

    // Default: disabled
    return false;
  }

  async setFlag(flag: string, enabled: boolean, scope?: { companyId?: string; workspaceId?: string }): Promise<void> {
    const key = scope?.companyId
      ? `ff:${flag}:company:${scope.companyId}`
      : scope?.workspaceId
        ? `ff:${flag}:workspace:${scope.workspaceId}`
        : `ff:${flag}`;
    await this.redis.set(key, String(enabled));
  }
}
```

### Feature Flag Usage Pattern

```typescript
// In any service — check before executing new behavior
@Injectable()
export class CampaignService {
  constructor(
    private readonly featureFlags: FeatureFlagService,
    private readonly tenantContext: DomainContext,
  ) {}

  async createCampaign(dto: CreateCampaignDto) {
    // Gate new feature behind flag, scoped to company
    if (await this.featureFlags.isEnabled('advanced-scheduling', {
      companyId: this.tenantContext.companyId,
    })) {
      return this.createWithAdvancedScheduling(dto);
    }
    return this.createBasic(dto);
  }
}
```

### Feature Flag Rules

| Rule | Why |
|------|-----|
| Every breaking change behind a flag | Instant rollback without redeploy |
| Flags scoped to company for UC3 (MSSP) | Different companies get different features |
| Flags have an expiry date in comments | Prevent flag debt — clean up after 2 sprints |
| Flags are documented in a central registry | Team knows what flags exist and their state |
| Never nest feature flags | Combinatorial explosion — one flag per behavior change |
| Test both paths | CI must test flag=on and flag=off |

### Feature Flag Registry Pattern

```typescript
// feature-flags/registry.ts — single source of truth
export const FEATURE_FLAGS = {
  'advanced-scheduling': {
    description: 'Advanced campaign scheduling with timezone support',
    defaultEnabled: false,
    scope: 'company',           // 'global' | 'company' | 'workspace'
    addedDate: '2025-03-01',
    expectedRemoval: '2025-05-01',
    owner: 'team-campaigns',
  },
  'drizzle-recipients': {
    description: 'Use Drizzle ORM for new recipient queries',
    defaultEnabled: false,
    scope: 'global',
    addedDate: '2025-02-15',
    expectedRemoval: '2025-04-15',
    owner: 'team-platform',
  },
} as const satisfies Record<string, {
  description: string;
  defaultEnabled: boolean;
  scope: 'global' | 'company' | 'workspace';
  addedDate: string;
  expectedRemoval: string;
  owner: string;
}>;

export type FeatureFlag = keyof typeof FEATURE_FLAGS;
```

---

## DEPLOYMENT STRATEGIES

### Strategy Selection

| Strategy | When to Use | Rollback Speed | Risk |
|----------|-------------|----------------|------|
| Rolling update | Standard deploys, no schema changes | ~30s | Low |
| Blue-green | Schema migrations, major version bumps | Instant (switch LB) | Medium |
| Canary | Risky changes, performance-sensitive | ~10s (kill canary) | Lowest |

### Rolling Update (Default)

```
Old v1  Old v1  Old v1       ← Start: 3 replicas running v1
Old v1  Old v1  New v2       ← Step 1: Replace one replica
Old v1  New v2  New v2       ← Step 2: Replace second replica
New v2  New v2  New v2       ← Step 3: All replaced
```

**Requirements:**
- Health check passes before routing traffic to new instance
- Graceful shutdown: drain connections, finish in-flight requests (30s timeout)
- Backward-compatible schema (additive migrations only)

### Blue-Green Deployment

```
                +-- Blue (v1) ← Current production (active)
Load Balancer --+
                +-- Green (v2) ← New version (warming up)

Step 1: Deploy v2 to Green environment
Step 2: Run smoke tests against Green
Step 3: Switch Load Balancer to Green
Step 4: Monitor for 5 minutes
Step 5: If healthy, tear down Blue. If not, switch back.
```

**When required:**
- Database migrations that change column types (via multi-step pattern)
- Major dependency upgrades
- Infrastructure changes (new Redis cluster, new DB version)

### Canary Deployment

```
Load Balancer
  |-- 95% --> Stable (v1) [3 replicas]
  |--  5% --> Canary (v2) [1 replica]

Monitor for 15 minutes:
  - Error rate: canary vs stable
  - Latency p99: canary vs stable
  - Queue processing rate

If healthy: promote canary to stable (rolling update)
If unhealthy: kill canary, 100% back to stable
```

---

## BULLMQ WORKER DEPLOYMENT

### Separation Principle

**Workers MUST be separate containers from the API.** Never run BullMQ processors inside the NestJS HTTP process in production.

```
# WRONG — workers in API process
api:
  command: npm run start:prod  # handles HTTP + jobs

# RIGHT — separate worker process
api:
  command: npm run start:prod  # HTTP only
worker:
  command: npm run start:worker  # jobs only
```

### Worker Scaling

```yaml
# Scale workers independently based on queue depth
# docker compose up --scale worker=3
worker:
  image: ${REGISTRY}/api:${TAG}       # Same image as API
  command: ["node", "dist/worker.js"]  # Different entrypoint
  deploy:
    replicas: 2
    resources:
      limits:
        memory: 512M
        cpus: '0.5'
```

### Worker Entrypoint

```typescript
// src/worker.ts — separate entry point, NOT main.ts
import { NestFactory } from '@nestjs/core';
import { WorkerModule } from './worker.module';

async function bootstrap() {
  const app = await NestFactory.createApplicationContext(WorkerModule);

  // Graceful shutdown
  const signals: NodeJS.Signals[] = ['SIGTERM', 'SIGINT'];
  for (const signal of signals) {
    process.on(signal, async () => {
      console.log(`Received ${signal}, shutting down gracefully...`);
      // BullMQ workers will finish current job before stopping
      await app.close();
      process.exit(0);
    });
  }

  console.log('Worker started');
}

bootstrap();
```

### Worker Module

```typescript
// src/worker.module.ts — imports job processors, NOT controllers
@Module({
  imports: [
    ConfigModule.forRoot(),
    BullModule.forRootAsync({
      useFactory: (config: ConfigService) => ({
        connection: {
          host: config.get('BULL_REDIS_HOST'),
          port: config.get('BULL_REDIS_PORT'),
          password: config.get('BULL_REDIS_PASSWORD'),
        },
      }),
      inject: [ConfigService],
    }),
    // Register ALL queues that workers process
    BullModule.registerQueue(
      { name: 'import' },
      { name: 'bulk-operations' },
      { name: 'email-send' },
      { name: 'notifications' },
    ),
    // Import ONLY modules needed by processors
    DatabaseModule,
    RedisModule,
  ],
  providers: [
    ImportProcessor,
    BulkOperationsProcessor,
    EmailSendProcessor,
    NotificationProcessor,
  ],
})
export class WorkerModule {}
```

### Graceful Shutdown for Workers

```typescript
// Every processor must handle graceful shutdown
@Processor('import')
export class ImportProcessor extends WorkerHost {
  async process(job: Job) {
    const batchSize = 500;
    const total = job.data.rows.length;

    for (let i = 0; i < total; i += batchSize) {
      // Check if worker is shutting down
      if (job.token && await job.isActive()) {
        const batch = job.data.rows.slice(i, i + batchSize);
        await this.processBatch(batch, job.data.tenantContext);
        await job.updateProgress(Math.round(((i + batchSize) / total) * 100));
      } else {
        // Job will be retried by another worker
        throw new Error('Worker shutting down, job will retry');
      }
    }
  }
}
```

---

## HEALTH CHECKS

### Health Check Endpoint Pattern

```typescript
// health/health.controller.ts
@Controller('health')
export class HealthController {
  constructor(
    private health: HealthCheckService,
    private db: PrismaHealthIndicator,
    private redis: RedisHealthIndicator,
    private bullmq: BullMQHealthIndicator,
  ) {}

  @Get()
  @HealthCheck()
  async check() {
    return this.health.check([
      // Database: can we run a simple query?
      () => this.db.pingCheck('database', { timeout: 3000 }),
      // Redis: can we ping?
      () => this.redis.pingCheck('redis', { timeout: 1000 }),
      // BullMQ: are queues responsive?
      () => this.bullmq.check('bullmq', { timeout: 2000 }),
    ]);
  }

  // Liveness probe — is the process alive?
  @Get('live')
  live() {
    return { status: 'ok', timestamp: new Date().toISOString() };
  }

  // Readiness probe — can the process serve traffic?
  @Get('ready')
  @HealthCheck()
  async ready() {
    return this.health.check([
      () => this.db.pingCheck('database', { timeout: 1000 }),
      () => this.redis.pingCheck('redis', { timeout: 500 }),
    ]);
  }
}
```

### Health Check Response Shape

```json
{
  "status": "ok",
  "info": {
    "database": { "status": "up", "responseTime": 12 },
    "redis": { "status": "up", "responseTime": 2 },
    "bullmq": { "status": "up", "activeJobs": 3, "waitingJobs": 12 }
  },
  "error": {},
  "details": {
    "database": { "status": "up", "responseTime": 12 },
    "redis": { "status": "up", "responseTime": 2 },
    "bullmq": { "status": "up", "activeJobs": 3, "waitingJobs": 12 }
  }
}
```

### Custom Health Indicators

```typescript
// health/redis-health.indicator.ts
@Injectable()
export class RedisHealthIndicator extends HealthIndicator {
  constructor(@Inject('REDIS') private readonly redis: Redis) {
    super();
  }

  async pingCheck(key: string, options: { timeout: number }): Promise<HealthIndicatorResult> {
    const start = Date.now();
    try {
      const result = await Promise.race([
        this.redis.ping(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), options.timeout)),
      ]);
      if (result !== 'PONG') throw new Error(`Unexpected response: ${result}`);
      return this.getStatus(key, true, { responseTime: Date.now() - start });
    } catch (error) {
      throw new HealthCheckError('Redis check failed', this.getStatus(key, false, { error: error.message }));
    }
  }
}

// health/bullmq-health.indicator.ts
@Injectable()
export class BullMQHealthIndicator extends HealthIndicator {
  constructor(
    @InjectQueue('import') private importQueue: Queue,
    @InjectQueue('bulk-operations') private bulkQueue: Queue,
  ) {
    super();
  }

  async check(key: string, options: { timeout: number }): Promise<HealthIndicatorResult> {
    try {
      const [importCounts, bulkCounts] = await Promise.all([
        this.importQueue.getJobCounts(),
        this.bulkQueue.getJobCounts(),
      ]);
      const totalActive = importCounts.active + bulkCounts.active;
      const totalWaiting = importCounts.waiting + bulkCounts.waiting;
      const totalFailed = importCounts.failed + bulkCounts.failed;

      // Alert if failed jobs are piling up
      const isHealthy = totalFailed < 100;
      return this.getStatus(key, isHealthy, {
        activeJobs: totalActive,
        waitingJobs: totalWaiting,
        failedJobs: totalFailed,
      });
    } catch (error) {
      throw new HealthCheckError('BullMQ check failed', this.getStatus(key, false, { error: error.message }));
    }
  }
}
```

---

## MASTER CHECKLIST

### Pre-Deployment Checklist

**Code Quality:**
- [ ] All tests pass (`npm run test` + `npm run test:e2e`)
- [ ] TypeScript compiles with zero errors (`npm run build`)
- [ ] Linting passes (`npm run lint`)
- [ ] No `console.log` in production code (use structured logger)
- [ ] No hardcoded secrets, URLs, or environment-specific values

**Database:**
- [ ] Migrations are additive only (no renames, no drops, no type changes)
- [ ] Migration tested against a copy of production data
- [ ] Prisma migrations: `npx prisma migrate deploy` succeeds
- [ ] Drizzle migrations: `npx drizzle-kit migrate` succeeds
- [ ] TimescaleDB setup scripts are idempotent
- [ ] Rollback script exists for data migrations

**Docker:**
- [ ] Docker image builds successfully
- [ ] Image size is reasonable (<500MB for API, <300MB for frontend)
- [ ] Health check endpoint responds correctly
- [ ] Container runs as non-root user
- [ ] No secrets baked into image layers

**Feature Flags:**
- [ ] Breaking changes are behind feature flags
- [ ] Feature flag registry is updated
- [ ] Both flag=on and flag=off paths are tested
- [ ] Flag has an expiry date and owner

### Post-Deployment Checklist

**Immediate (0-5 minutes):**
- [ ] Health check endpoint returns `status: ok`
- [ ] Application logs show successful startup (no error-level logs)
- [ ] Key API endpoints respond (smoke test)
- [ ] Database connections are established
- [ ] Redis connection is established
- [ ] BullMQ workers are processing jobs

**Short-term (5-30 minutes):**
- [ ] Error rate is at or below pre-deployment baseline
- [ ] Latency p99 is at or below pre-deployment baseline
- [ ] No increase in 5xx responses
- [ ] Queue depth is not growing unexpectedly
- [ ] Memory usage is stable (no leaks)

**Medium-term (30 minutes - 2 hours):**
- [ ] Cron jobs and scheduled tasks execute correctly
- [ ] Background job completion rate is normal
- [ ] No tenant-specific errors in logs
- [ ] Sentry error count is not elevated

### Rollback Procedure

```
Step 1: DECIDE — Is this a rollback situation?
  - 5xx rate > 1% for 5 minutes
  - p99 latency > 3x baseline for 5 minutes
  - Any data corruption detected
  - Critical feature broken for any tenant

Step 2: ROLLBACK APPLICATION
  Option A (preferred): Revert commit on main, redeploy
    git revert HEAD --no-edit && git push
  Option B (fast): Redeploy previous image tag
    deploy --image ${REGISTRY}/api:${PREVIOUS_TAG}
  Option C (instant): Feature flag
    Set flag to 'false' — new code path disabled, no redeploy needed

Step 3: ROLLBACK MIGRATIONS (only if needed)
  - Additive migrations: NO rollback needed (old code ignores new columns)
  - Data migrations: Run reverse migration script
  - NEVER drop columns that the previous code version uses

Step 4: NOTIFY
  - Post in #deployments channel
  - Create incident ticket
  - Document what went wrong and what triggered the rollback

Step 5: POST-MORTEM
  - Within 24 hours
  - Blameless — focus on process, not people
  - Action items with owners and deadlines
```

---

## SECRETS MANAGEMENT

### Secret Hierarchy

```
Development:  .env file (git-ignored, developer-local)
CI/CD:        GitHub Actions Secrets (encrypted, org-level)
Staging:      Cloud provider secret manager (AWS SSM / GCP Secret Manager)
Production:   Cloud provider secret manager + rotation policy
```

### Rules

| Rule | Why |
|------|-----|
| Never commit secrets | Git history is forever — even if you delete the file |
| Never log secrets | Structured logging makes accidental exposure easy to search |
| Never pass secrets as CLI args | `ps aux` shows process arguments to all users |
| Rotate secrets on any suspected exposure | Assume compromise, act immediately |
| Use separate secrets per environment | Staging compromise must not affect production |
| Audit secret access | Cloud provider logs show who accessed which secret when |

### Secret Rotation Checklist

```
1. Generate new secret value
2. Add new secret to secret manager (don't remove old yet)
3. Update application to accept BOTH old and new (grace period)
4. Deploy application
5. Verify application works with new secret
6. Remove old secret from secret manager
7. Deploy to remove grace period code (accept new only)
```

---

## NETWORK SECURITY

### Container Network Rules

```yaml
# docker-compose.yml network segmentation
networks:
  frontend:        # Next.js only — exposed to load balancer
  backend:         # NestJS API — exposed to load balancer + frontend
  data:            # PostgreSQL + Redis — NOT exposed to internet
  monitoring:      # Grafana, Prometheus — internal only

# Services attach to ONLY the networks they need
services:
  frontend:
    networks: [frontend, backend]    # Can reach API
  api:
    networks: [backend, data]        # Can reach DB + Redis
  postgres:
    networks: [data]                 # Reachable only by API + workers
  redis:
    networks: [data]                 # Reachable only by API + workers
  worker:
    networks: [backend, data]        # Can reach DB + Redis
```

### Port Exposure Rules

| Service | Internal Port | External Port | Notes |
|---------|-------------|---------------|-------|
| Next.js | 3000 | 443 (via LB) | HTTPS only |
| NestJS API | 3001 | 443 (via LB) | HTTPS only, `/api/*` path |
| PostgreSQL | 5432 | NONE | Internal only |
| Redis | 6379 | NONE | Internal only |
| Bull Board | 3002 | NONE | Internal only, VPN access |
| Grafana | 3003 | NONE | Internal only, VPN access |
