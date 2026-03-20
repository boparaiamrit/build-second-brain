# Library Decisions Reference — Pre-Evaluated Technology Choices

> Read this file when Phase 0 (Library Selection) is triggered by a new
> infrastructure concern or external integration.

---

## Job Queues

| Library | Pros | Cons | Verdict |
|---------|------|------|---------|
| **BullMQ** | NestJS native module, Redis-backed, retry/backoff, job groups, Bull Board UI, actively maintained | Redis dependency | **✅ DEFAULT** |
| **Temporal** | Durable workflows, visibility dashboard, replay, multi-step sagas | Complex infra, steep learning curve | Multi-step workflows only |
| **Agenda** | MongoDB-backed, cron-style | Older, weak NestJS support | ❌ Avoid |
| **pg-boss** | PostgreSQL-backed, exactly-once, no Redis | Smaller ecosystem | Only if no Redis |

**Decision:** BullMQ for everything. Temporal only if you need multi-step durable sagas.

---

## Identity / SSO Providers

| Provider | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Passport.js** | NestJS native, 500+ strategies, flexible | Verbose, middleware model | **✅ OAuth flows** |
| **WorkOS** | Drop-in enterprise SSO (SAML, SCIM, Directory Sync) | Per-connection pricing | ✅ Fastest to market |
| **Keycloak** | Enterprise-grade, SAML/OIDC/LDAP/AD, full admin UI, free | Heavy Java service | Enterprise on-prem |
| **Auth0** | Hosted, pre-built MFA, enterprise features | Cost at scale, vendor lock-in | Good early stage |

**Decision:** Passport.js + Adapter pattern for flexibility. WorkOS if speed-to-market matters more.

### SSO Adapter Libraries

| Provider | Library | Reason |
|----------|---------|--------|
| Microsoft AD | `@azure/msal-node` | Microsoft-maintained, full MSAL, token cache |
| Google Workspace | `googleapis` | Official, TypeScript types |
| Okta | `@okta/okta-sdk-nodejs` | Full Groups + Users + SCIM |
| SAML 2.0 | `samlify` | Flexible, NestJS friendly |

---

## Audit Log Storage

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| PostgreSQL table | Same DB, easy joins, no extra infra | Grows large | **✅ Start here** |
| ClickHouse | Column-store, fast aggregations | Extra infra | >100M rows |
| Elasticsearch | Full-text search, Kibana UI | Expensive, complex | If search needed |
| BigQuery | Cheap archive, analytics-ready | Latency | Compliance export |

**Decision:** PostgreSQL → archival job → BigQuery after 90 days.

---

## File Parsing (Imports)

| Library | Format | Notes |
|---------|--------|-------|
| `papaparse` | CSV | Streaming parser, handles malformed CSVs |
| `exceljs` | XLSX | Full read/write, streaming mode for large files |
| `xlsx` (SheetJS) | XLSX/CSV | Faster parsing, but less streaming support |

**Decision:** `papaparse` for CSV, `exceljs` for XLSX (streaming mode for >100K rows).

---

## Email Sending

| Provider | Pros | Cons | Verdict |
|----------|------|------|---------|
| **AWS SES** | Cheap at scale, reliable, webhook support | Setup complexity | **✅ Production** |
| **Resend** | Modern DX, TypeScript SDK, React email | Newer, smaller scale | Good for dev/MVP |
| **Postmark** | Great deliverability, fast | Per-email pricing | Transactional only |
| **SendGrid** | Feature-rich, marketing tools | Twilio ownership concerns | Avoid for new projects |

**Decision:** AWS SES for production. Resend for early stage. Adapter pattern to swap later.

---

## File Storage

| Provider | Pros | Cons | Verdict |
|----------|------|------|---------|
| **AWS S3** | Industry standard, cheap, presigned URLs | AWS lock-in | **✅ Default** |
| **Cloudflare R2** | S3-compatible, no egress fees | Smaller ecosystem | Cost-sensitive |
| **MinIO** | Self-hosted S3-compatible | Ops overhead | On-prem requirement |

**Decision:** S3 with presigned URLs for uploads. Adapter pattern for portability.

---

## Observability

| Concern | Tool | Reason |
|---------|------|--------|
| Logging | `pino` + `nestjs-pino` | Structured JSON, fast, NestJS native |
| APM/Tracing | OpenTelemetry + Jaeger | Vendor-neutral, distributed tracing |
| Metrics | Prometheus + Grafana | Industry standard, free |
| Error tracking | Sentry (`@sentry/nestjs`) | Rich context, source maps, alerting |

---

## Feature Flags

| Provider | Pros | Cons | Verdict |
|----------|------|------|---------|
| **LaunchDarkly** | Enterprise-grade, targeting rules | Expensive | Enterprise |
| **Unleash** | Open source, self-hosted | Ops overhead | **✅ Best balance** |
| **ConfigCat** | Simple, cheap | Limited targeting | Small team |
| **Custom (Redis)** | No dependency, full control | No UI, no audit | MVP only |

**Decision:** Unleash for production. Redis flags for MVP.

---

## Research Template (Fill Before Writing ANY New Adapter)

```
API: [Name of external API / service]

LIBRARY OPTIONS:
1. [library-a] — pros: ... | cons: ... | last release: ... | weekly npm downloads: ...
2. [library-b] — pros: ... | cons: ...
3. Raw fetch — pros: no dependency | cons: no token mgmt, no retry

RECOMMENDATION: [library] because [specific reason]

FAILURE MODES:
- Token expiry mid-operation → handled by: [solution]
- Rate limit hit → handled by: [solution]
- Provider outage → handled by: [solution]
- Webhook tampered → handled by: [solution]

PAGINATION:
- Strategy: [cursor / page token / offset / Link header]
- Max page size: [N]
- Rule: always paginate to completion in background job, never sync

WEBHOOK VALIDATION:
- Method: [HMAC-SHA256 / signature header / bearer token]
- Header: [header name]
```
