# Threat Model Reference — STRIDE Analysis, Attack Trees, Tenant Isolation Verification

> Read this file when performing threat modeling on new features, auditing tenant isolation,
> planning penetration tests, or analyzing attack surfaces across the multi-tenant SaaS stack.

---

## Table of Contents
1. [Threat Model Template](#threat-model-template)
2. [STRIDE Analysis: NestJS API](#stride-analysis-nestjs-api)
3. [STRIDE Analysis: Redis Cache](#stride-analysis-redis-cache)
4. [STRIDE Analysis: BullMQ Workers](#stride-analysis-bullmq-workers)
5. [STRIDE Analysis: PostgreSQL](#stride-analysis-postgresql)
6. [STRIDE Analysis: File Upload/Import](#stride-analysis-file-uploadimport)
7. [STRIDE Analysis: Webhook System](#stride-analysis-webhook-system)
8. [Attack Trees](#attack-trees)
9. [Tenant Isolation Verification Checklist](#tenant-isolation-verification-checklist)
10. [Penetration Test Guide](#penetration-test-guide)

---

## Threat Model Template

Apply this template to every new feature before writing code.

### Step 1 — Asset Identification

| Question | Answer Format |
|----------|---------------|
| What data does this feature create, read, update, or delete? | List each data type (PII, credentials, tenant config, billing, etc.) |
| Which tables are touched? | List table names with columns |
| What is the sensitivity classification? | Public / Internal / Confidential / Restricted |
| Which tenant scopes are involved? | Company / Workspace / Domain / Cross-tenant |

### Step 2 — Actor Enumeration

| Actor | Trust Level | Capabilities |
|-------|-------------|-------------|
| Anonymous (unauthenticated) | None | Can reach public endpoints only |
| Authenticated User | Low | Read/write own workspace data via CASL abilities |
| Workspace Admin | Medium | Manage users, settings, domains within one workspace |
| Company Admin | High | Read all workspaces in company, write with explicit workspace scope |
| Company Owner | High | Full CRUD across all company workspaces |
| Platform Admin (internal) | Elevated | Impersonation, cross-company read via admin panel |
| System / BullMQ Worker | Internal | Processes jobs with tenant context from payload |
| External API Consumer | Varies | API key with scoped permissions |
| Attacker (external) | Hostile | Attempts to bypass every layer |
| Attacker (compromised account) | Hostile | Has valid credentials for one tenant, targets others |

### Step 3 — Entry Point Mapping

| Entry Point | Protocol | Auth Required | Rate Limited | Example |
|-------------|----------|---------------|-------------|---------|
| REST API | HTTPS | Yes (JwtAuthGuard) | Yes (per-IP, per-tenant) | `POST /domains/:domainId/recipients` |
| SSE Stream | HTTPS (long-lived) | Yes | Connection limit | `GET /domains/:domainId/jobs/:jobId/progress` |
| Webhook Inbound | HTTPS | HMAC signature | Per-source IP | `POST /webhooks/:provider` |
| Webhook Outbound | HTTPS | N/A (we initiate) | Per-tenant queue | Delivery to user-provided URL |
| File Upload | HTTPS (presigned S3) | Yes (signed URL) | Size + count limit | `PUT <presigned-url>` |
| BullMQ Job | Redis (internal) | Implicit (network) | Per-tenant rate | Job added to queue |
| Admin Panel | HTTPS | AdminJwtGuard + MFA | Strict per-IP | `GET /admin/workspaces` |
| SSO Callback | HTTPS | OAuth state param | Per-provider | `GET /auth/sso/callback` |

### Step 4 — Trust Boundary Diagram

```
+------------------------------------------------------------------+
|  INTERNET (Untrusted)                                            |
|  [Browser]  [Mobile]  [API Consumer]  [Webhook Source]           |
+---------|-------------|---------------|-------------|-------------+
          |             |               |             |
==========|=============|===============|=============|=== TLS BOUNDARY
          |             |               |             |
+---------v-------------v---------------v-------------v------------+
|  EDGE LAYER (DMZ)                                                |
|  WAF / DDoS Protection / TLS Termination / IP Allowlisting      |
+---------|--------------------------------------------------------+
          |
+---------v--------------------------------------------------------+
|  APPLICATION LAYER (Trusted Network)                             |
|                                                                  |
|  +------------------+    +------------------+                    |
|  | Next.js SSR      |    | NestJS API       |                   |
|  | (port 3000)      |--->| (port 3001)      |                   |
|  | Session cookies  |    | JWT validation   |                   |
|  +------------------+    | TenantContext     |                   |
|                          | CASL abilities    |                   |
|                          +--------|----------+                   |
|                                   |                              |
|  =================================|===== TENANT TRUST BOUNDARY   |
|                                   |                              |
|  +------------------+    +--------v---------+                    |
|  | Redis            |    | PostgreSQL       |                    |
|  | (port 6379)      |    | (port 5432)      |                   |
|  | Sessions, Cache  |    | Tenant data      |                   |
|  | Job state        |    | companyId scope   |                  |
|  +--------|----------+    | workspaceId scope |                  |
|           |              | domainId scope    |                   |
|  +--------v---------+    +------------------+                    |
|  | BullMQ Workers   |                                            |
|  | Job processing   |                                            |
|  | Tenant context   |                                            |
|  | from payload     |                                            |
|  +------------------+                                            |
+------------------------------------------------------------------+
```

### Step 5 — STRIDE Table (Fill Per Entry Point)

| # | Threat Category | Threat Description | Affected Asset | Likelihood | Impact | Risk | Mitigation |
|---|----------------|-------------------|----------------|-----------|--------|------|------------|
| 1 | Spoofing | _How can an attacker impersonate a legitimate actor?_ | | L/M/H | L/M/H/C | | |
| 2 | Tampering | _How can an attacker modify data in transit or at rest?_ | | L/M/H | L/M/H/C | | |
| 3 | Repudiation | _How can an actor deny performing an action?_ | | L/M/H | L/M/H/C | | |
| 4 | Info Disclosure | _How can data leak to unauthorized parties?_ | | L/M/H | L/M/H/C | | |
| 5 | Denial of Service | _How can an attacker degrade or halt the service?_ | | L/M/H | L/M/H/C | | |
| 6 | Elevation of Privilege | _How can a user gain unauthorized permissions?_ | | L/M/H | L/M/H/C | | |

**Risk calculation:** Likelihood x Impact. C = Critical (production data breach).

---

## STRIDE Analysis: NestJS API

HTTP API surface on port 3001. All tenant data flows through here.

### Spoofing

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| S1 | JWT forgery | Attacker crafts JWT with stolen/guessed signing key | Low | Critical | RS256 or EdDSA key pair (not HS256 shared secret). Keys in vault, rotated quarterly. Validate `iss`, `aud`, `exp` on every request. |
| S2 | Session replay | Attacker captures JWT from network traffic or XSS | Medium | Critical | Short-lived access tokens (15min). HttpOnly Secure SameSite=Strict cookies. TLS everywhere. No localStorage tokens. |
| S3 | API key theft | Attacker extracts API key from client code or logs | Medium | High | Keys hashed at rest (show last 4 only). Per-key scope limits. IP allowlist per key. Key rotation API. |
| S4 | SSO token swap | Attacker replays OAuth callback with different state | Low | High | Validate `state` parameter against server-side session. Single-use authorization codes. Short code expiry (10min). |
| S5 | Impersonation token theft | Attacker intercepts `x-impersonation-token` header | Low | Critical | 1-hour max TTL, non-renewable. Transmitted only over TLS. Token invalidated on admin logout. Bound to admin IP. |
| S6 | Workspace header spoofing | Attacker sets `x-workspace-id` to another tenant | High | Critical | TenantContextGuard validates header against JWT claims. Never trust client-provided tenant IDs alone. |

### Tampering

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| T1 | Request body modification | Attacker adds extra fields (mass assignment) | Medium | High | `whitelist: true` + `forbidNonWhitelisted: true` in ValidationPipe. DTOs define exact allowed fields. |
| T2 | Header injection | CRLF characters in custom headers | Low | Medium | NestJS pipes strip `\r\n` from header-bound input. Helmet.js adds protective headers. |
| T3 | Parameter pollution | Duplicate query params (`?domainId=a&domainId=b`) | Medium | High | Express parses first value by default. Explicit param extraction in controller (not spreading query). |
| T4 | JSON prototype pollution | `__proto__` or `constructor` in request body | Low | High | `forbidNonWhitelisted: true` strips unknown keys. Use `Object.create(null)` for lookup maps. |
| T5 | IDOR via URL params | `GET /domains/other-domain-id/recipients` | High | Critical | Repository WHERE clause uses `domainId` from `tenantContext` (resolved server-side), not URL param alone. URL param validated against context. |

### Repudiation

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| R1 | Missing mutation audit | Developer forgets `@Audit` decorator on new endpoint | High | High | Linter rule to require `@Audit` on all POST/PATCH/DELETE. PR checklist item. |
| R2 | Audit log tampering | Attacker with DB access modifies audit_logs table | Low | Critical | Append-only table (no UPDATE/DELETE grants for app user). Integrity hash chain. Write-once storage for exports. |
| R3 | Admin action deniability | Admin performs destructive action without trail | Medium | High | `logSync()` (synchronous) for all admin operations. Impersonation requires mandatory `reason` field. |
| R4 | Unsigned outbound webhooks | Recipient disputes receiving webhook payload | Medium | Medium | HMAC-SHA256 signature on every delivery. Include timestamp. Log delivery attempts with response codes. |

### Information Disclosure

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| I1 | Stack traces in errors | Unhandled exception returns internal paths and code | Medium | Medium | Global exception filter returns safe messages. Never expose stack traces outside dev. Sentry captures full trace server-side. |
| I2 | Timing attacks on auth | Login response time differs for valid vs invalid emails | Medium | Low | Constant-time comparison for passwords. Same response time and message for "invalid email" and "wrong password". |
| I3 | Cache data leak | Shared Redis key returns another tenant's data | High | Critical | ALL cache keys prefixed with tenant scope: `domain:{domainId}:*`. Never use global keys for tenant data. |
| I4 | Verbose API responses | Response includes internal IDs, timestamps, or metadata not needed by client | Medium | Low | Response DTOs (serialization) strip internal fields. `@Exclude()` on sensitive columns. Never return `password`, `apiKeyHash`, etc. |
| I5 | Error-based enumeration | Different HTTP status codes for "not found" vs "forbidden" | Medium | Medium | Return 403 (not 404) when resource exists but user lacks access. Prevents existence leaking. |
| I6 | SSE event leakage | SSE stream includes events from other domains | Medium | Critical | SSE filter uses `domainId` from server-resolved `tenantContext`, not client header. |

### Denial of Service

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| D1 | Unbounded query | `GET /recipients?limit=999999` | High | High | Max page size enforced in DTO validation (`@Max(100)`). Default 50. |
| D2 | Queue flooding | Attacker submits thousands of import/bulk jobs | Medium | High | Per-tenant job rate limits (e.g., 5 imports/hour). Dedup key prevents duplicate active jobs. |
| D3 | ReDoS | Regex in search filter causes catastrophic backtracking | Medium | High | No user input in regex. Use `ilike` for search, not `SIMILAR TO` or app-level regex. Validate input length before processing. |
| D4 | Large request body | 100MB JSON payload exhausts memory | Medium | Medium | `json({ limit: '1mb' })` middleware. File uploads via presigned S3 URLs (never through API body). |
| D5 | Slowloris / slow read | Attacker sends headers very slowly to hold connections | Medium | Medium | Reverse proxy (nginx) with `client_header_timeout` and `client_body_timeout`. Connection limits per IP. |
| D6 | SSE connection exhaustion | Open thousands of SSE connections | Medium | Medium | Max SSE connections per user (5). Per-IP connection limit at load balancer. Auto-close after job completes. |

### Elevation of Privilege

| # | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|--------|--------------|-----------|--------|------------|
| E1 | Role escalation via API | User sends `{ "role": "company_admin" }` in profile update | Medium | Critical | Role field excluded from user-facing update DTOs. Role changes require admin endpoint + CASL check. |
| E2 | Tenant hopping | Authenticated user changes workspace/domain context to another tenant | High | Critical | TenantContextGuard validates every request against JWT claims. Workspace membership verified. |
| E3 | Impersonation to admin panel | Admin impersonates user, then navigates to `/admin/*` | Low | Critical | AdminJwtGuard rejects tokens with `isImpersonated: true`. Admin routes are a separate auth chain. |
| E4 | Cross-workspace write | Company Admin reads workspace B but writes to it without proper role | Medium | High | Write operations require explicit `workspaceId` validated against user role in THAT workspace. Read != Write permission. |
| E5 | Subscription bypass | Expired subscription tenant still creates resources | Medium | High | TenantContextGuard checks `subscriptionStatus` on every request. CASL `cannot('create', 'all')` for inactive subs. |

---

## STRIDE Analysis: Redis Cache

Redis on port 6379. Stores sessions, tenant context cache, job progress, rate limit counters.

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| RC1 | Spoofing | Session hijacking | Attacker obtains session key from Redis (via network sniff or SSRF) | Low | Critical | Redis AUTH required. TLS in production. Bind to internal network only. Session keys include device fingerprint. |
| RC2 | Spoofing | Tenant context spoofing | Attacker writes fake `domain:{id}:context` key to Redis | Low | Critical | App user has no direct Redis access. Redis `rename-command` disables `FLUSHALL`, `CONFIG`, `DEBUG`. Network isolation. |
| RC3 | Tampering | Cache poisoning | Attacker modifies cached tenant context to change `subscriptionTier` or `companyId` | Low | Critical | Redis behind AUTH + TLS + network isolation. Cache entries have TTL (1 hour). Context re-fetched from DB on miss. |
| RC4 | Tampering | Tenant key collision | Two tenants have overlapping cache keys due to missing scope prefix | High | Critical | ALL keys MUST include tenant scope: `domain:{domainId}:*`. Linter/code review rule: reject bare keys. |
| RC5 | Repudiation | Session invalidation gap | User changes password but old sessions remain valid in Redis | Medium | High | On password change: `KEYS session:{userId}:*` then `DEL`. On role change: invalidate affected sessions. |
| RC6 | Info Disclosure | Session data exposure | Redis dump includes session data with role and tenant info | Low | Medium | Redis RDB/AOF files encrypted at rest. Sensitive fields (tokens) not stored in Redis — only references. |
| RC7 | Info Disclosure | Cache timing attack | Measuring response time reveals cache hit (data exists) vs miss (no data) | Low | Low | Not typically exploitable for tenant data. If needed: add small random delay to cache-miss path. |
| RC8 | DoS | Memory exhaustion | Attacker triggers massive cache writes (e.g., unique filter combinations) | Medium | High | `maxmemory-policy: allkeys-lru`. TTL on all keys. Max key size limits. Monitor memory usage with alerts. |
| RC9 | DoS | Eviction-based DoS | Attacker floods cache causing legitimate tenant data eviction | Medium | Medium | LRU eviction is acceptable — cache miss falls through to DB. Critical data (sessions) uses separate Redis instance or keyspace. |
| RC10 | Elevation | Session manipulation | Attacker modifies cached session to escalate role | Low | Critical | Session data is server-written only. Redis AUTH prevents external writes. Session tokens are opaque (validated server-side). |

---

## STRIDE Analysis: BullMQ Workers

BullMQ workers process background jobs via Redis-backed queues. Every job carries `tenantContext` in its payload.

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| BQ1 | Spoofing | Tenant context spoofing in job | Attacker injects job with fake `tenantContext` pointing to another tenant | Low | Critical | Jobs added only via service layer (not direct queue access). Processor validates `tenantContext` against DB before processing. Network isolation on Redis. |
| BQ2 | Tampering | Job payload tampering | Attacker modifies job data in Redis between enqueue and processing | Low | Critical | Redis AUTH + network isolation. Job IDs include tenant scope: `{queueName}:{domainId}:{timestamp}`. Processors validate payload schema. |
| BQ3 | Tampering | Job result injection | Attacker writes fake completion data to `job:{jobId}:progress` | Low | Medium | Progress keys written only by worker process. SSE endpoint reads progress but never writes. Redis ACL (Redis 6+) to restrict key patterns per client. |
| BQ4 | Repudiation | Missing job audit trail | Job completes or fails without logging | Medium | High | BaseProcessor `finally` block writes to `job_logs` table on every execution (success and failure). Dead letter queue for final failures. |
| BQ5 | Repudiation | Admin retry without logging | Admin retries failed job without audit | Low | Medium | Admin retry endpoint uses `@Audit('admin.job_retried')`. Original job ID preserved in retry metadata. |
| BQ6 | Info Disclosure | Job data leak across tenants | Worker logs or error messages include tenant data from another job | Medium | High | Structured logging with `tenantContext` fields. Error messages sanitized before Sentry. Job payloads never logged in full at INFO level. |
| BQ7 | Info Disclosure | Bull Board exposure | Bull Board dashboard exposed without auth | Medium | High | Bull Board behind `AdminJwtGuard` + `AdminMfaGuard`. VPN-only access in production. |
| BQ8 | DoS | Queue flooding | Attacker submits thousands of jobs via rapid API calls | Medium | High | Per-tenant job rate limits: `job-rate:{queueName}:{companyId}`. Dedup key: `active_job:{workspaceId}:{queueName}` prevents duplicate active jobs. |
| BQ9 | DoS | Worker resource exhaustion | Malicious job payload (e.g., 10M row import) consumes all worker memory | Medium | High | Import size limits per plan (free: 1K, pro: 50K, enterprise: 500K rows). Workers process in batches (500 rows). Worker memory limits via container constraints. |
| BQ10 | DoS | Stuck job blocking queue | Job hangs indefinitely, blocking queue concurrency slot | Medium | Medium | `timeout` on job options (e.g., 30 minutes for imports). Stalled job detection enabled. `stalledInterval` configured. |
| BQ11 | Elevation | Cross-tenant job result access | User polls progress SSE for another tenant's job | Medium | High | SSE endpoint validates `domainId` in URL against `tenantContext`. Job ID alone is insufficient for access — tenant scope required. |

---

## STRIDE Analysis: PostgreSQL

PostgreSQL on port 5432 with TimescaleDB extension. All tenant data has `companyId`, `workspaceId`, `domainId` columns.

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| PG1 | Spoofing | DB user impersonation | Attacker obtains app DB credentials | Low | Critical | Dedicated app user with minimum grants (SELECT/INSERT/UPDATE on app tables, no SUPERUSER). Credentials in vault, rotated quarterly. Different users for app vs migration vs admin. |
| PG2 | Tampering | SQL injection | Unsanitized user input in query string | Low | Critical | Drizzle ORM parameterizes all queries. No raw `sql` template with string interpolation. Code review rule: reject `sql\`...${userInput}...\`` without parameterization. |
| PG3 | Tampering | Missing WHERE clause | Developer forgets `domainId` in query, returns all-tenant data | High | Critical | Repository pattern: `domainId` is ALWAYS the first WHERE condition. Mandatory code review for any raw query. Integration tests verify cross-tenant isolation per module. |
| PG4 | Tampering | Migration tampering | Attacker modifies migration file to alter schema destructively | Low | High | Migrations in version control with checksum verification. Migration user separate from app user. CI validates migration checksums before apply. |
| PG5 | Repudiation | Audit log bypass | Direct DB write bypasses application audit layer | Low | High | App user has no INSERT grant on audit_logs — only the audit service DB user can write. Trigger-based audit as secondary layer for critical tables. |
| PG6 | Info Disclosure | Connection string exposure | `DATABASE_URL` leaked via error message, log, or env dump | Medium | Critical | Connection string in vault (not `.env` in production). Error filter strips connection details. `pg_hba.conf` restricts source IPs. |
| PG7 | Info Disclosure | Query plan leak | `EXPLAIN ANALYZE` output reveals table structure and data distribution | Low | Low | `EXPLAIN` disabled for app user. Only DBA/migration user can run `EXPLAIN`. |
| PG8 | Info Disclosure | Backup exposure | Database backup file accessible without encryption | Low | Critical | Backups encrypted at rest (cloud KMS). Backup bucket has no public access. Separate backup encryption key from app key. Retention policy enforced (90 days). |
| PG9 | DoS | Connection pool exhaustion | Attacker opens max connections, blocking legitimate requests | Medium | High | Connection pool with max size (e.g., 20 per service instance). Idle timeout (30s). Statement timeout (30s for queries, 5min for migrations). |
| PG10 | DoS | Expensive query | Unindexed filter on large table causes sequential scan | High | Medium | Required indexes: `(domain_id)` on every data table. `(domain_id, created_at)` for pagination. `statement_timeout = 30s` kills runaway queries. |
| PG11 | DoS | Table lock escalation | Long-running migration locks table, blocking all reads/writes | Medium | High | Online migrations only (no `ALTER TABLE ... ADD COLUMN ... DEFAULT` on large tables in pre-PG11). Use `CREATE INDEX CONCURRENTLY`. Migration timeouts. |
| PG12 | Elevation | Privilege escalation via DB user | App DB user granted excessive permissions | Medium | Critical | Principle of least privilege: app user gets SELECT/INSERT/UPDATE/DELETE on app tables only. No CREATE, ALTER, DROP, SUPERUSER. Separate users per concern (app, migration, audit, backup). |

---

## STRIDE Analysis: File Upload/Import

File imports (CSV, XLSX) via presigned S3 URLs. Processing in BullMQ workers.

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| FU1 | Spoofing | Presigned URL theft | Attacker intercepts presigned upload URL and uploads malicious file | Low | High | Presigned URLs expire in 5 minutes. URLs scoped to specific key path including `domainId`. One-time use via S3 condition. |
| FU2 | Tampering | Malicious file content (code exec) | Attacker uploads file containing macros (XLSX) or embedded scripts | Medium | Critical | Never execute uploaded files. Parse CSV with papaparse (text-only). Parse XLSX with exceljs in read-only mode. Strip macros. Sandbox worker process. |
| FU3 | Tampering | CSV injection | Cell starting with `=`, `+`, `-`, `@` triggers formula execution when opened in Excel | High | Medium | Prefix cells starting with formula characters with a single quote (`'`). Document risk to users. Sanitize on import AND on export. |
| FU4 | Tampering | File type spoofing | Attacker renames `.exe` to `.csv` and uploads | Medium | High | Validate file content (magic bytes), not just extension. Allowlist: `.csv`, `.xlsx` only. Reject everything else. Content-Type validation server-side. |
| FU5 | Tampering | Zip bomb (XLSX) | Malicious XLSX with extreme compression ratio exhausts worker memory | Medium | High | Limit decompressed size (100MB max). Stream-parse XLSX (do not load entire file into memory). Worker memory limits via container constraints. |
| FU6 | Repudiation | Import without audit | Large import completes without recording who imported what | Medium | High | `import_jobs` table records: who, when, file name, row counts. `@Audit('recipients.import_committed')` on commit endpoint. |
| FU7 | Info Disclosure | Import file accessible to other tenants | S3 key path does not include tenant scope | Medium | Critical | S3 key pattern: `imports/{companyId}/{workspaceId}/{domainId}/{jobId}/{filename}`. Bucket policy denies cross-prefix access. |
| FU8 | Info Disclosure | Error messages reveal file system paths | Import processor error includes server file path | Medium | Low | Catch all processor errors. Return safe messages: "Row 42: invalid email format". Never expose temp file paths. |
| FU9 | DoS | Import volume DoS | Attacker uploads 10M-row CSV to exhaust DB writes and worker time | Medium | High | Plan-based limits: free=1K, pro=50K, enterprise=500K rows. Validation phase counts rows before commit. Reject oversized files early. |
| FU10 | DoS | Concurrent import flooding | Attacker starts 100 imports simultaneously | Medium | Medium | Dedup key: `active_job:{domainId}:import` — one active import per domain. Queue rate limit: 5 imports/hour per tenant. |
| FU11 | Elevation | Import into wrong domain | Import processor uses domainId from file metadata instead of tenant context | Low | Critical | `domainId` comes from `tenantContext` in job payload (resolved server-side at job creation). Never from file content. |
| FU12 | Info Disclosure | SSRF via URL import | Feature to import from URL: attacker provides internal URL (`http://169.254.169.254/...`) | High | Critical | If URL import exists: validate URL with `validateOutboundUrl()` (deny private IPs, require HTTPS). DNS resolution check for rebinding. Timeout (5s). Size limit (50MB). |

---

## STRIDE Analysis: Webhook System

Outbound webhooks (platform delivers events to customer URLs) and inbound webhooks (external providers send events to platform).

### Outbound Webhooks (Platform -> Customer URL)

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| WO1 | Spoofing | Webhook forgery | Customer cannot verify webhook is genuinely from platform | Medium | Medium | HMAC-SHA256 signature in `X-Webhook-Signature` header. Per-tenant signing secret. Include timestamp to prevent replay. |
| WO2 | Tampering | Payload modification in transit | MITM modifies webhook body between platform and customer | Low | Medium | HTTPS-only delivery. Signature covers entire body. Customer verifies signature before processing. |
| WO3 | Repudiation | Delivery dispute | Customer claims they never received webhook | Medium | Medium | Log every delivery attempt: URL, response code, response time, retry count. Expose delivery log in UI. |
| WO4 | Info Disclosure | Sensitive data in payload | Webhook body includes PII or credentials not needed by recipient | Medium | High | Webhook payloads use minimal schema — IDs and event type, not full records. Customer fetches details via API if needed. Never include passwords, tokens, or full PII. |
| WO5 | Info Disclosure | SSRF via customer URL | Customer registers `http://169.254.169.254/latest/meta-data/` as webhook URL | High | Critical | `validateOutboundUrl()` on registration AND on each delivery. Deny private IPs (10.x, 172.16.x, 192.168.x, 127.x, 169.254.x, ::1, fc00::, fe80::). DNS re-check before each delivery (prevents DNS rebinding). |
| WO6 | DoS | Webhook delivery exhaustion | Customer URL is slow (30s response), backing up delivery queue | Medium | Medium | 5-second timeout per delivery. Exponential backoff (5s, 30s, 2min, 15min, 1hr). Disable webhook after 5 consecutive failures. |
| WO7 | Elevation | Cross-tenant webhook delivery | Webhook event from tenant A delivered to tenant B's URL | Low | Critical | Webhook registrations scoped to `workspaceId`. Event routing validates tenant match before delivery. |

### Inbound Webhooks (Provider -> Platform)

| # | Category | Threat | Attack Vector | Likelihood | Impact | Mitigation |
|---|----------|--------|--------------|-----------|--------|------------|
| WI1 | Spoofing | Forged inbound webhook | Attacker sends fake webhook pretending to be Stripe/SendGrid/etc. | High | High | Verify provider signature (HMAC or asymmetric). Stripe: `stripe.webhooks.constructEvent()`. SendGrid: ECDSA verification. Reject unsigned requests. |
| WI2 | Tampering | Replay attack | Attacker captures legitimate webhook and replays it | Medium | Medium | Check timestamp in webhook (reject if >5 min old). Idempotency key: store processed webhook IDs, reject duplicates. |
| WI3 | Tampering | Signature bypass | Attacker attempts to bypass signature with crafted headers | Medium | High | Use provider SDK for verification (not custom code). Verify exact header name. Reject requests missing signature header entirely. |
| WI4 | Info Disclosure | Webhook endpoint enumeration | Attacker discovers webhook paths by scanning | Low | Low | Webhook paths include random token: `/webhooks/{provider}/{random-token}`. Return 404 (not 401) for invalid paths. |
| WI5 | DoS | Webhook flood | Attacker sends thousands of fake webhooks | Medium | Medium | Rate limit webhook endpoints per source IP. Signature verification before any processing (fail fast). Queue webhook processing via BullMQ (don't block HTTP). |
| WI6 | Elevation | Webhook triggers cross-tenant action | Payment webhook for company A triggers subscription change for company B | Low | Critical | Webhook payload includes customer/subscription ID. Resolve to internal tenant. Validate match before applying action. |

---

## Attack Trees

### Attack Tree 1: Cross-Tenant Data Access

The highest-risk scenario. Attacker authenticated as Tenant A accesses Tenant B data.

```
GOAL: Access Tenant B data as Tenant A user
|
+-- [1] Bypass TenantContextGuard
|   |
|   +-- [1.1] Spoof workspace header
|   |   |-- Send x-workspace-id: <tenant-B-workspace>
|   |   +-- BLOCKED: Guard validates header against JWT claims
|   |
|   +-- [1.2] Find endpoint missing guard
|   |   |-- Scan for @Public() on data endpoints
|   |   +-- MITIGATED: Code review checklist, linter rule
|   |
|   +-- [1.3] Exploit SSE stream without scope
|       |-- Connect to SSE endpoint with cross-tenant jobId
|       +-- BLOCKED: SSE validates domainId from tenantContext
|
+-- [2] Exploit Cache Layer
|   |
|   +-- [2.1] Cache key collision
|   |   |-- Trigger cache write with key lacking tenant prefix
|   |   +-- MITIGATED: All keys prefixed domain:{domainId}:
|   |
|   +-- [2.2] Cache poisoning via Redis access
|       |-- Gain direct Redis access (SSRF or network breach)
|       +-- BLOCKED: Redis AUTH + network isolation + TLS
|
+-- [3] Exploit Database Layer
|   |
|   +-- [3.1] SQL injection to bypass WHERE
|   |   |-- Inject into search/filter parameter
|   |   +-- BLOCKED: Drizzle parameterized queries
|   |
|   +-- [3.2] Missing domainId in WHERE clause
|   |   |-- Find query that fetches by primary key without domain scope
|   |   +-- MITIGATED: Repository pattern, mandatory isolation tests
|   |
|   +-- [3.3] IDOR on resource ID
|       |-- Guess/enumerate UUID of Tenant B resource
|       +-- BLOCKED: Repository adds domainId filter, returns 403
|
+-- [4] Exploit Background Jobs
|   |
|   +-- [4.1] Inject job with Tenant B context
|   |   |-- Submit API request that enqueues job with wrong tenant
|   |   +-- BLOCKED: Job tenantContext comes from request.tenantContext (server-resolved)
|   |
|   +-- [4.2] Read Tenant B job progress
|       |-- Poll SSE with Tenant B jobId
|       +-- BLOCKED: SSE endpoint validates tenant scope
|
+-- [5] Exploit Admin Impersonation
    |
    +-- [5.1] Compromise admin account
    |   |-- Phishing, credential stuffing on admin login
    |   +-- MITIGATED: MFA required, IP allowlist, 1hr token max
    |
    +-- [5.2] Escalate impersonation scope
        |-- Impersonation token used beyond target workspace
        +-- BLOCKED: Token bound to specific workspaceId, validated per request
```

### Attack Tree 2: Admin Account Compromise

Second highest risk. Platform admin accounts have cross-tenant visibility.

```
GOAL: Compromise platform admin account
|
+-- [1] Credential Theft
|   |
|   +-- [1.1] Phishing admin email
|   |   |-- Social engineering to capture admin password
|   |   +-- MITIGATED: MFA (TOTP/WebAuthn) required for all admin routes
|   |
|   +-- [1.2] Credential stuffing
|   |   |-- Automated login with breached credential lists
|   |   +-- BLOCKED: Account lockout after 5 attempts, IP rate limiting
|   |
|   +-- [1.3] Session theft (XSS)
|       |-- Inject script to steal admin session cookie
|       +-- BLOCKED: HttpOnly + Secure + SameSite=Strict cookies. CSP blocks inline scripts.
|
+-- [2] Privilege Escalation
|   |
|   +-- [2.1] Role manipulation via API
|   |   |-- Modify own user record to set role=super_admin
|   |   +-- BLOCKED: Role not in user-facing update DTO. Admin roles managed by separate system.
|   |
|   +-- [2.2] Exploit admin API without MFA check
|   |   |-- Find admin endpoint missing AdminMfaGuard
|   |   +-- MITIGATED: All /admin/* routes require MFA guard. Code review checklist.
|   |
|   +-- [2.3] Bypass impersonation controls
|       |-- Impersonate user, then access admin panel
|       +-- BLOCKED: AdminJwtGuard rejects isImpersonated=true tokens
|
+-- [3] Post-Compromise Actions (if admin compromised)
    |
    +-- [3.1] Mass data export
    |   |-- Use admin panel to export all tenant data
    |   +-- DETECTED: Bulk export triggers alert at >10K records. Audit log captures all admin actions.
    |
    +-- [3.2] Impersonate high-value users
    |   |-- Use impersonation to act as any user
    |   +-- DETECTED: Impersonation logged (sync), alerts after 30min. Max 1hr session.
    |
    +-- [3.3] Modify tenant configurations
        |-- Change subscription tiers, disable security settings
        +-- DETECTED: @Audit on all admin mutations. Role changes trigger alerts.
```

### Attack Tree 3: Bulk Data Exfiltration

Third highest risk. Attacker extracts large volumes of tenant data.

```
GOAL: Exfiltrate bulk tenant data (>10K records)
|
+-- [1] Via API (Authenticated)
|   |
|   +-- [1.1] Paginate through all records
|   |   |-- Loop GET /recipients?offset=0,50,100...
|   |   +-- DETECTED: Rate limit per tenant (100 req/min). Alert on >10K reads in 1hr.
|   |
|   +-- [1.2] Export endpoint abuse
|   |   |-- POST /domains/:id/recipients/export
|   |   +-- DETECTED: Export logged with record count. Alert at >10K. CASL 'export' permission required.
|   |
|   +-- [1.3] Search filter bypass
|       |-- Use broad filter to return maximum results
|       +-- MITIGATED: Max page size 100. Total pagination depth limited.
|
+-- [2] Via File Import/Export
|   |
|   +-- [2.1] Export to S3 and steal presigned URL
|   |   |-- Intercept download URL for exported file
|   |   +-- MITIGATED: Presigned URLs expire in 5min. Scoped to tenant S3 prefix.
|   |
|   +-- [2.2] Import staging table exfil
|       |-- Access import_staging_rows with data from multiple imports
|       +-- BLOCKED: Staging rows scoped by domainId. Deleted after commit.
|
+-- [3] Via Database Direct Access
|   |
|   +-- [3.1] SQL injection to COPY/dump
|   |   |-- Inject SQL to export table to file
|   |   +-- BLOCKED: Drizzle parameterized queries. App user has no COPY permission.
|   |
|   +-- [3.2] Backup file theft
|       |-- Access unencrypted backup from storage
|       +-- BLOCKED: Backups encrypted at rest. Bucket policy denies public access.
|
+-- [4] Via Background Jobs
|   |
|   +-- [4.1] Trigger bulk export job with elevated scope
|   |   |-- Manipulate job payload to export all domains
|   |   +-- BLOCKED: Job tenantContext from server-resolved request context.
|   |
|   +-- [4.2] Intercept job results
|       |-- Read Redis keys for completed export jobs
|       +-- BLOCKED: Redis AUTH + network isolation. Results scoped by tenant.
|
+-- [5] Via Admin Compromise (see Attack Tree 2)
    |
    +-- [5.1] Impersonate users across tenants sequentially
        |-- Export from each tenant individually
        +-- DETECTED: Impersonation audit trail. Alert on multiple impersonations in short window.
```

---

## Tenant Isolation Verification Checklist

Manual verification process to confirm tenant isolation. Run before any major release.

### Test Environment Setup

Create the following test hierarchy:

```
Company-A (companyId: comp-a)
  +-- Workspace-A1 (workspaceId: ws-a1)
  |     +-- Domain-A1a (domainId: dom-a1a) -- 100 test recipients
  |     +-- Domain-A1b (domainId: dom-a1b) -- 100 test recipients
  +-- Workspace-A2 (workspaceId: ws-a2)
        +-- Domain-A2a (domainId: dom-a2a) -- 100 test recipients

Company-B (companyId: comp-b)
  +-- Workspace-B1 (workspaceId: ws-b1)
  |     +-- Domain-B1a (domainId: dom-b1a) -- 100 test recipients
  +-- Workspace-B2 (workspaceId: ws-b2)
        +-- Domain-B2a (domainId: dom-b2a) -- 100 test recipients
```

**Test users (one per role per context):**

| User | Role | Company | Workspace | Expected Access |
|------|------|---------|-----------|-----------------|
| user-a1 | user | Company-A | Workspace-A1 | dom-a1a + dom-a1b only |
| admin-a1 | workspace_admin | Company-A | Workspace-A1 | dom-a1a + dom-a1b (manage) |
| admin-a2 | workspace_admin | Company-A | Workspace-A2 | dom-a2a only |
| cadmin-a | company_admin | Company-A | (all) | ws-a1 + ws-a2 (read all, write with scope) |
| owner-a | company_owner | Company-A | (all) | Full CRUD across Company-A |
| user-b1 | user | Company-B | Workspace-B1 | dom-b1a only |
| admin-b1 | workspace_admin | Company-B | Workspace-B1 | dom-b1a (manage) |

### Test Matrix

Run each test case. Mark PASS/FAIL. Any FAIL is a P0 blocker.

#### Cross-Company Isolation (MUST all pass)

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 1 | List recipients cross-company | user-a1 | `GET /domains/dom-b1a/recipients` | 403 Forbidden |
| 2 | Get recipient by ID cross-company | user-a1 | `GET /domains/dom-b1a/recipients/:id` (ID from Company-B) | 403 Forbidden |
| 3 | Create recipient cross-company | admin-a1 | `POST /domains/dom-b1a/recipients` | 403 Forbidden |
| 4 | Update recipient cross-company | admin-a1 | `PATCH /domains/dom-b1a/recipients/:id` | 403 Forbidden |
| 5 | Delete recipient cross-company | owner-a | `DELETE /domains/dom-b1a/recipients/:id` | 403 Forbidden |
| 6 | Export cross-company | cadmin-a | `POST /domains/dom-b1a/recipients/export` | 403 Forbidden |
| 7 | Import to cross-company domain | admin-a1 | `POST /domains/dom-b1a/recipients/imports/upload-url` | 403 Forbidden |
| 8 | SSE stream cross-company | user-a1 | `GET /domains/dom-b1a/jobs/:jobId/progress` | 403 Forbidden |
| 9 | Settings read cross-company | cadmin-a | `GET /workspaces/ws-b1/settings` | 403 Forbidden |
| 10 | Webhook register cross-company | admin-a1 | `POST /workspaces/ws-b1/webhooks` | 403 Forbidden |

#### Cross-Workspace Isolation (Same Company)

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 11 | List recipients cross-workspace | user-a1 | `GET /domains/dom-a2a/recipients` | 403 Forbidden |
| 12 | Create in sibling workspace | admin-a1 | `POST /domains/dom-a2a/recipients` | 403 Forbidden |
| 13 | Company Admin read cross-ws | cadmin-a | `GET /domains/dom-a2a/recipients` | 200 OK (read allowed) |
| 14 | Company Admin write without scope | cadmin-a | `POST /domains/dom-a2a/recipients` (no explicit ws header) | 403 Forbidden |
| 15 | Company Admin write with scope | cadmin-a | `POST /domains/dom-a2a/recipients` (x-workspace-id: ws-a2) | 200 OK (if has write role in ws-a2) |
| 16 | Settings modify cross-workspace | admin-a1 | `PATCH /workspaces/ws-a2/settings` | 403 Forbidden |
| 17 | User list in sibling workspace | admin-a1 | `GET /workspaces/ws-a2/users` | 403 Forbidden |

#### Cross-Domain Isolation (Same Workspace)

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 18 | List recipients wrong domain | user-a1 (scoped to dom-a1a) | `GET /domains/dom-a1b/recipients` | 200 OK (same workspace, user has access) |
| 19 | Verify no data leakage | user-a1 | `GET /domains/dom-a1a/recipients` | Returns ONLY dom-a1a recipients (not dom-a1b) |
| 20 | Domain filter integrity | user-a1 | `GET /domains/dom-a1a/recipients?search=*` | Results scoped to dom-a1a only |

#### Cache Isolation

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 21 | Cache key isolation | admin-a1 | List recipients (dom-a1a), then switch to dom-b1a | Cache miss on dom-b1a (no stale data from dom-a1a) |
| 22 | Session isolation | user-a1 | Authenticate, then replay session token as user-b1 | Session bound to user-a1 identity, cannot act as user-b1 |
| 23 | Cache invalidation scope | admin-a1 | Update recipient in dom-a1a | Only dom-a1a cache invalidated, dom-a1b cache untouched |

#### Job Isolation

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 24 | Import job tenant scope | admin-a1 | Start import on dom-a1a, verify job payload | `tenantContext.domainId` = dom-a1a, `companyId` = comp-a |
| 25 | Cross-tenant job progress | user-b1 | Poll SSE for admin-a1's import job | 403 Forbidden |
| 26 | Job result isolation | admin-a1 | Complete import, verify data scoped | New recipients have `domainId` = dom-a1a, `companyId` = comp-a |

#### Impersonation Boundaries

| # | Test | Actor | Action | Expected Result |
|---|------|-------|--------|----------------|
| 27 | Impersonation token at admin route | platform-admin (impersonating user-a1) | `GET /admin/workspaces` | 403 Forbidden (isImpersonated=true rejected) |
| 28 | Impersonation cross-company | platform-admin (impersonating user-a1) | `GET /domains/dom-b1a/recipients` | 403 Forbidden (impersonation bound to user-a1's workspace) |
| 29 | Impersonation expiry | platform-admin | Use token after 1 hour | 401 Unauthorized |
| 30 | Impersonation audit | platform-admin | Perform any action while impersonating | Audit log shows `actorType: admin_impersonation` |

---

## Penetration Test Guide

### Scope and Methodology

Map OWASP Testing Guide v4.2 categories to this stack.

| OWASP Category | What to Test in This Stack | Priority |
|----------------|---------------------------|----------|
| WSTG-INFO: Information Gathering | Service fingerprinting, error message verbosity, headers | Medium |
| WSTG-CONF: Configuration Management | CORS, CSP, security headers, Redis/PG exposure | High |
| WSTG-IDNT: Identity Management | User registration, account enumeration, username policy | Medium |
| WSTG-ATHN: Authentication | JWT validation, session management, SSO flows, MFA bypass | Critical |
| WSTG-ATHZ: Authorization | RBAC/ABAC bypass, IDOR, tenant isolation, role escalation | Critical |
| WSTG-SESS: Session Management | Cookie attributes, session fixation, concurrent sessions | High |
| WSTG-INPV: Input Validation | SQL injection, XSS, SSRF, file upload, CSV injection | Critical |
| WSTG-ERRH: Error Handling | Stack traces, error-based enumeration, debug endpoints | Medium |
| WSTG-CRYP: Cryptography | TLS config, password hashing, key management, token entropy | High |
| WSTG-BUSL: Business Logic | Subscription bypass, rate limit evasion, workflow abuse | High |
| WSTG-CLNT: Client-Side | DOM XSS, clickjacking, WebSocket hijacking, postMessage abuse | Medium |
| WSTG-APIT: API Testing | REST-specific: mass assignment, verb tampering, rate limiting | Critical |

### Tools

| Tool | Purpose | Usage in This Stack |
|------|---------|---------------------|
| Burp Suite Pro | HTTP proxy, active/passive scanning, request manipulation | Intercept all API calls, test auth bypass, IDOR, injection |
| sqlmap | Automated SQL injection detection | Target search/filter parameters, custom field queries |
| Nuclei | Template-based vulnerability scanning | Scan for misconfig (CORS, headers, exposed endpoints) |
| ffuf | Fuzzing endpoints and parameters | Discover hidden API routes, test input validation |
| jwt_tool | JWT analysis, manipulation, and attack | Test JWT forgery (none alg, key confusion, expired tokens) |
| Postman/httpie | Manual API testing with auth flows | Reproduce tenant isolation tests from checklist above |
| OWASP ZAP | Automated web app scanning (free alternative to Burp) | Passive scan for XSS, CSRF, security headers |
| Redis CLI | Direct Redis inspection | Verify key patterns, test AUTH, check for exposed data |
| pgcli/psql | Direct PostgreSQL inspection | Verify grants, check for injection sinks, test constraints |

### Test Scenarios with Payloads

#### 1. Authentication Bypass

```
# Test: JWT none algorithm attack
# Tool: jwt_tool or manual

# Original JWT header: {"alg":"RS256","typ":"JWT"}
# Attack: change to {"alg":"none","typ":"JWT"} and remove signature
# Expected: 401 Unauthorized (server MUST reject alg:none)

# Test: Expired token acceptance
# Modify JWT exp claim to past timestamp
curl -H "Authorization: Bearer <expired-jwt>" \
  https://api.example.com/domains/dom-a1a/recipients
# Expected: 401 Unauthorized

# Test: Token from different environment/issuer
# Use JWT signed by different key
# Expected: 401 Unauthorized (signature validation fails)
```

#### 2. Tenant Isolation (IDOR)

```
# Test: Direct object reference across tenants
# Authenticated as user-a1 (Company A)

# Attempt to read Company B recipient by UUID
curl -H "Authorization: Bearer <user-a1-token>" \
  -H "x-domain-id: dom-a1a" \
  https://api.example.com/domains/dom-b1a/recipients/rec-b1a-001
# Expected: 403 Forbidden

# Attempt header spoofing
curl -H "Authorization: Bearer <user-a1-token>" \
  -H "x-workspace-id: ws-b1" \
  -H "x-domain-id: dom-b1a" \
  https://api.example.com/domains/dom-b1a/recipients
# Expected: 403 Forbidden (guard validates header against JWT)

# Attempt domain ID swap in URL
curl -H "Authorization: Bearer <user-a1-token>" \
  https://api.example.com/domains/dom-b1a/recipients
# Expected: 403 Forbidden
```

#### 3. SQL Injection

```
# Test: Search parameter injection
# Target: GET /domains/:domainId/recipients?search=<payload>

# Payloads (adapt for Drizzle/PostgreSQL):
search=' OR '1'='1
search=' UNION SELECT id,email,password FROM users--
search='; DROP TABLE recipients;--
search=' AND (SELECT CASE WHEN (1=1) THEN pg_sleep(5) ELSE pg_sleep(0) END)--

# Expected: Empty results or validation error. Never SQL error. Never delay (time-based).
# If any payload returns data or causes delay: CRITICAL finding.

# Test: Custom field filter injection
# Target: POST /domains/:domainId/recipients/filter
# Body: { "customFields": { "department': ''; DROP TABLE--": "value" } }
# Expected: Validation error (invalid key format). Never SQL error.
```

#### 4. SSRF (Webhooks and URL Import)

```
# Test: Webhook registration with internal URL
curl -X POST -H "Authorization: Bearer <token>" \
  -d '{"url":"http://169.254.169.254/latest/meta-data/","events":["recipient.created"]}' \
  https://api.example.com/workspaces/ws-a1/webhooks
# Expected: 400 Bad Request (private IP rejected)

# Test: DNS rebinding
# Register webhook with domain that resolves to public IP, then rebind to 127.0.0.1
# Expected: Re-validated on each delivery attempt

# Test: URL import with internal target
curl -X POST -H "Authorization: Bearer <token>" \
  -d '{"url":"http://10.0.0.1:5432/","type":"csv"}' \
  https://api.example.com/domains/dom-a1a/recipients/imports/from-url
# Expected: 400 Bad Request (private IP rejected)

# Additional SSRF payloads:
http://127.0.0.1:6379/       # Redis
http://[::1]:3001/            # IPv6 loopback
http://0x7f000001:3001/       # Hex IP
http://localhost:5432/         # PostgreSQL
http://metadata.google.internal/  # Cloud metadata (GCP)
```

#### 5. File Upload Attacks

```
# Test: Malicious file type
# Upload .exe renamed to .csv
# Expected: Rejected (magic bytes check fails)

# Test: CSV injection
# Upload CSV with formula cells:
# =CMD|'/C calc'!A0
# +CMD|'/C calc'!A0
# -1+1|'/C calc'!A0
# @SUM(1+1)*cmd|'/C calc'!A0
# Expected: Cells prefixed with ' on import. Warning in preview.

# Test: Oversized file
# Upload 500MB CSV file (exceeds plan limit)
# Expected: Rejected during validation phase with clear error message

# Test: Zip bomb XLSX
# Create XLSX with extreme compression ratio (1KB compressed -> 1GB decompressed)
# Expected: Worker rejects when decompressed size exceeds 100MB limit
```

#### 6. Rate Limit Evasion

```
# Test: Auth endpoint brute force
for i in $(seq 1 20); do
  curl -X POST -d '{"email":"admin@company.com","password":"attempt'$i'"}' \
    https://api.example.com/auth/login
done
# Expected: 429 Too Many Requests after 5-10 attempts. Account locked after 5 failures.

# Test: Rate limit bypass via headers
curl -H "X-Forwarded-For: 1.2.3.4" \
  -H "X-Real-IP: 1.2.3.4" \
  https://api.example.com/auth/login
# Expected: Rate limit uses true client IP (from trusted proxy), not spoofed header

# Test: API key rate limit per tenant
for i in $(seq 1 200); do
  curl -H "x-api-key: <key>" \
    https://api.example.com/domains/dom-a1a/recipients?page=$i
done
# Expected: 429 after tenant rate limit exceeded
```

#### 7. Privilege Escalation

```
# Test: Mass assignment on user update
curl -X PATCH -H "Authorization: Bearer <user-token>" \
  -d '{"firstName":"John","role":"company_admin","isAdmin":true}' \
  https://api.example.com/users/me
# Expected: role and isAdmin fields ignored (not in DTO). Only firstName updated.

# Test: Subscription bypass
# With expired subscription token:
curl -X POST -H "Authorization: Bearer <expired-sub-token>" \
  -d '{"email":"new@test.com","firstName":"New"}' \
  https://api.example.com/domains/dom-a1a/recipients
# Expected: 403 Forbidden (subscription inactive)

# Test: Access admin routes as regular user
curl -H "Authorization: Bearer <regular-user-token>" \
  https://api.example.com/admin/workspaces
# Expected: 403 Forbidden (AdminJwtGuard rejects non-admin tokens)
```

### Reporting Findings

Use the severity framework from SKILL.md. Every finding MUST include:

| Field | Description | Example |
|-------|-------------|---------|
| **ID** | Unique finding identifier | VULN-2026-001 |
| **Title** | One-line description | Cross-tenant recipient access via IDOR |
| **Severity** | CRITICAL / HIGH / MEDIUM / LOW | CRITICAL |
| **CVSS Score** | Calculated CVSS v3.1 score | 9.1 |
| **Component** | Affected service/module | NestJS API > RecipientsController |
| **Endpoint** | Specific route | `GET /domains/:domainId/recipients/:id` |
| **Description** | Detailed explanation of the vulnerability | TenantContextGuard not applied to individual recipient lookup... |
| **Reproduction** | Step-by-step with exact payloads | 1. Authenticate as user-a1. 2. Send GET... |
| **Impact** | What an attacker can achieve | Read any tenant's recipient data by guessing UUID |
| **Root Cause** | Why the vulnerability exists | Missing @UseGuards(TenantContextGuard) on findById route |
| **Remediation** | Specific fix with code reference | Add TenantContextGuard, add domainId to WHERE clause |
| **Evidence** | Screenshots, response bodies, logs | HTTP 200 with Tenant B data in response body |
| **Verification** | How to confirm the fix works | Re-run test case, expect 403. Add isolation test. |

**Severity mapping for this stack:**

| Severity | Criteria | Response SLA |
|----------|----------|-------------|
| CRITICAL | Cross-tenant data access, auth bypass, RCE, credential exposure | Fix within 24 hours |
| HIGH | Single-tenant escalation, significant data leak, SSRF to internal | Fix within 72 hours |
| MEDIUM | Information disclosure, missing security header, weak rate limit | Fix within 1 sprint |
| LOW | Verbose error, minor misconfiguration, theoretical attack | Fix within 1 quarter |
