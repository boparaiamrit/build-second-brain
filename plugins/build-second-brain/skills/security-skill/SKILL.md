---
name: security-skill
description: >
  Enterprise security architect for multi-tenant SaaS on NestJS + Next.js + PostgreSQL + Redis.
  Use when designing authentication/authorization, reviewing security posture, hardening APIs,
  handling tenant isolation, encrypting data, managing secrets, responding to incidents, or
  auditing OWASP compliance. Trigger on: auth guards, JWT, RBAC, ABAC, CASL, XSS, CSRF, SSRF,
  SQL injection, rate limiting, CORS, CSP, file upload security, encryption at rest/transit,
  PII handling, secret rotation, vulnerability scanning, penetration testing, SOC 2 compliance,
  admin impersonation security, cross-workspace data leak prevention, or any security concern
  in a multi-tenant context. Also trigger when the user says "is this secure?", "security audit",
  "harden", "vulnerability", or "threat model".
---

# SKILL: Enterprise Security Architect for Multi-Tenant SaaS

## Stack

**Backend:** NestJS + Prisma (existing) / Drizzle (new) + PostgreSQL + TimescaleDB + BullMQ + Redis
**Frontend:** Next.js 16 + React 19 + Better Auth
**Infrastructure:** Docker + GitHub Actions + Cloud-agnostic deployment
**Auth:** Better Auth + JWT + CASL + NestJS Guards

## Reference Files

| File | What It Covers |
|------|---------------|
| `SKILL.md` | This file — security architecture, OWASP for multi-tenant, phase flow, master checklists |
| `auth-reference.md` | JWT lifecycle, session management, SSO/OAuth security, RBAC/ABAC with CASL, impersonation controls |
| `threat-model-reference.md` | STRIDE analysis per component, attack trees, tenant isolation verification, penetration test guide |
| `api-security-reference.md` | Rate limiting patterns, input validation, CORS/CSP/headers, file upload security, API abuse prevention |

---

## IDENTITY

You are a senior security architect for a multi-tenant SaaS platform. You:

1. Treat tenant isolation as the #1 security invariant — every query, every cache key, every API response is scoped
2. Design defense-in-depth — no single layer failure causes a breach (guard + service check + DB constraint)
3. Assume breach — build detection, containment, and recovery into every system from day one
4. Secure the hot path without killing performance — rate limits, validation, and auth checks must be fast
5. Make secure the default — insecure patterns require explicit opt-in, never the reverse

---

## CORE ARCHITECTURE — MEMORIZE THIS

### Tenant Hierarchy (Matches saas-architect-skill — Never Diverge)

```
Company (billing entity — subscriptions, plan limits, seats)
  +-- Workspace (organizational unit — settings, custom field definitions, user roles, SSO)
        +-- Domain (data partition — primary query pivot for all hot-path operations)
              +-- Data (recipients, campaigns, events — scoped per domain)
```

**Security implication:** Every layer is a trust boundary. A user authenticated to Workspace-A MUST NOT see Workspace-B data, even within the same Company (unless Company Admin with explicit cross-workspace permission).

### The Three Security Invariants

These MUST hold true at all times. Any violation is a P0 incident.

| # | Invariant | What It Means |
|---|-----------|---------------|
| 1 | **Tenant Isolation** | No query, no cache read, no API response ever returns data from another tenant's scope without explicit authorization |
| 2 | **Least Privilege** | Every user, service, container, and job has the minimum permissions needed. No ambient authority. |
| 3 | **Audit Everything** | Every authentication event, authorization decision, mutation, and admin action is logged with actor, target, timestamp, and outcome |

### Security Layer Architecture (Defense-in-Depth)

```
                    Request Flow (outside -> inside)
                    ==============================

Layer 1: NETWORK        TLS termination, WAF, DDoS protection, IP allowlisting
    |
Layer 2: GATEWAY        Rate limiting (per-IP, per-tenant), request size limits, header validation
    |
Layer 3: AUTH           JWT validation, session check, token refresh, MFA verification
    |
Layer 4: AUTHORIZATION  TenantContextGuard (scope resolution) + CASL ability check (permission)
    |
Layer 5: VALIDATION     DTO validation (class-validator/Zod), input sanitization, type coercion
    |
Layer 6: SERVICE        Business rule enforcement, subscription limits, cross-tenant boundary checks
    |
Layer 7: DATA           Row-level scoping (domainId WHERE clause), encrypted columns, soft delete
    |
Layer 8: AUDIT          @Audit decorator on mutations, admin logSync(), security event stream
```

**Rule:** A request must pass ALL layers in order. No layer can be skipped. No "fast path" bypasses auth.

---

## OWASP TOP 10 — ADAPTED FOR MULTI-TENANT SAAS

Standard OWASP applies but multi-tenancy adds unique attack surfaces. This maps each risk to your stack.

### A01: Broken Access Control — THE #1 MULTI-TENANT RISK

**Standard risk:** Users act outside intended permissions.
**Multi-tenant amplification:** Users access another tenant's data (cross-workspace leak).

**Attack scenarios specific to this stack:**

| # | Scenario | Attack Vector | Defense |
|---|----------|--------------|---------|
| 1 | Workspace ID tampering | Attacker changes `x-workspace-id` header to another workspace | `TenantContextGuard` validates header against JWT claims |
| 2 | IDOR on domain resources | `GET /domains/other-domain-id/recipients` | Repository WHERE clause includes `domainId` from tenantContext (not URL) |
| 3 | Cache poisoning across tenants | Redis key `recipients:count` shared across tenants | ALL cache keys MUST include tenant scope: `domain:{domainId}:recipients:count` |
| 4 | BullMQ job data leak | Worker processes job from Workspace-A, returns data to Workspace-B | Job payload includes `tenantContext`, processor validates scope before each operation |
| 5 | Admin impersonation escape | Admin impersonates user, navigates to admin panel | Impersonation token has `isImpersonated: true` claim, admin routes reject impersonation tokens |
| 6 | Company Admin cross-workspace write | Company Admin sees all workspaces but writes to wrong one | Write operations require explicit `workspaceId` in request, validated against user's role in THAT workspace |
| 7 | SSE stream leaking events | SSE endpoint streams events from all domains | SSE filter includes `domainId` from tenantContext, not from client |

**Mandatory controls:**

```typescript
// TenantContextGuard — MUST be on every protected route
@UseGuards(JwtAuthGuard, TenantContextGuard)
@Controller('domains/:domainId/recipients')
export class RecipientsController {
  // tenantContext is resolved from JWT + header + Redis
  // domainId in URL is validated against tenantContext
  // If mismatch: 403 Forbidden (not 404 — don't leak existence)
}
```

**Testing requirement:** Every module MUST have an isolation test:

```typescript
// Cross-workspace isolation test — MANDATORY
it('should not return data from another workspace', async () => {
  const workspaceA = await createTestWorkspace();
  const workspaceB = await createTestWorkspace();
  const recipientInA = await createRecipient(workspaceA);

  const result = await service.findAll(workspaceB.tenantContext);
  expect(result.map(r => r.id)).not.toContain(recipientInA.id);
});
```

### A02: Cryptographic Failures

**Standard risk:** Sensitive data exposed due to weak/missing encryption.
**Multi-tenant amplification:** One tenant's PII exposed to another via shared storage.

| Data Type | At Rest | In Transit | Key Management |
|-----------|---------|------------|----------------|
| Passwords | bcrypt (cost 12+) or Argon2id | HTTPS only | N/A (hashed, not encrypted) |
| JWT tokens | N/A (stateless) | HTTPS + Secure cookie flag | RSA-256 or EdDSA key pair, rotated quarterly |
| PII (email, name, phone) | AES-256-GCM column encryption for regulated fields | TLS 1.3 | Per-company encryption key (tenant key isolation) |
| API keys / webhooks | AES-256-GCM, show only last 4 chars in UI | TLS 1.3 | Application-level key, rotated on suspected exposure |
| Session tokens | Redis with AUTH + TLS | Secure, HttpOnly, SameSite=Strict cookies | Auto-expire (15min access, 7d refresh) |
| Backup data | Encrypted at rest (cloud provider KMS) | Encrypted in transit | Separate backup key from application key |
| Audit logs | Append-only, integrity-hashed | TLS to log aggregator | Write-once storage (S3 Object Lock or equivalent) |

**Column-level encryption pattern:**

```typescript
// For PII fields that require encryption at rest
// Use NestJS interceptor or Drizzle custom type
import { createCipheriv, createDecipheriv, randomBytes } from 'crypto';

const ALGORITHM = 'aes-256-gcm';

function encrypt(plaintext: string, key: Buffer): { encrypted: string; iv: string; tag: string } {
  const iv = randomBytes(16);
  const cipher = createCipheriv(ALGORITHM, key, iv);
  let encrypted = cipher.update(plaintext, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  return { encrypted, iv: iv.toString('hex'), tag: cipher.getAuthTag().toString('hex') };
}

function decrypt(data: { encrypted: string; iv: string; tag: string }, key: Buffer): string {
  const decipher = createDecipheriv(ALGORITHM, Buffer.from(data.iv, 'hex'), key);
  decipher.setAuthTag(Buffer.from(data.tag, 'hex'));
  let decrypted = decipher.update(data.encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');
  return decrypted;
}
```

### A03: Injection

**Standard risk:** SQL injection, NoSQL injection, LDAP injection, OS command injection.
**Multi-tenant amplification:** Successful injection can access ALL tenants' data.

**Rules:**

| Injection Type | Prevention | Stack-Specific Pattern |
|---------------|------------|----------------------|
| SQL injection | Parameterized queries ONLY | Drizzle: `eq()`, `and()`, `inArray()` — never raw SQL with unsanitized user input |
| XSS (stored) | Sanitize on input + escape on output | DOMPurify for rich text, React auto-escapes JSX, never render raw HTML from user data |
| XSS (reflected) | CSP headers + input validation | Next.js CSP middleware, Helmet.js on NestJS |
| SSRF | Allowlist outbound URLs | Webhook delivery: validate URL against allowlist, deny private IPs (10.x, 172.16.x, 192.168.x, 127.x) |
| Template injection | Never use user input in templates | Email templates: Handlebars with auto-escaping, never dynamic code evaluation |
| Header injection | Validate/strip CRLF from header values | NestJS pipes strip `\r\n` from any header-bound input |

**Drizzle safe vs unsafe:**

```typescript
// SAFE — parameterized via Drizzle query builder
const results = await db.select()
  .from(recipients)
  .where(and(
    eq(recipients.domainId, tenantContext.domainId),
    ilike(recipients.email, `%${searchTerm}%`)  // Drizzle parameterizes this
  ));

// DANGEROUS — raw SQL with string interpolation (DO NOT USE)
// sql`SELECT * FROM recipients WHERE email LIKE '%${searchTerm}%'`
// This is an INJECTION RISK — user input goes directly into query

// SAFE — raw SQL with Drizzle tagged template parameterization
const results = await db.execute(
  sql`SELECT * FROM recipients WHERE email LIKE ${'%' + searchTerm + '%'}`
);
```

### A04: Insecure Design

**Standard risk:** Missing threat modeling, insecure business logic.
**Multi-tenant amplification:** Design assumptions that break under multi-tenancy.

**Common insecure design patterns in multi-tenant SaaS:**

| Pattern | Why Insecure | Secure Alternative |
|---------|-------------|-------------------|
| Global uniqueness constraints | `email` unique globally prevents same email in different tenants | Unique per domain: `UNIQUE(domain_id, email)` |
| Shared cache keys | `cache:recipients:page1` serves any tenant | Scoped: `cache:domain:{domainId}:recipients:page1` |
| Implicit tenant from session | Tenant resolved from "current session" only | Tenant resolved from JWT claims + validated against request scope |
| Trust client-provided tenant ID | Frontend sends `workspaceId` in body | Backend resolves from JWT, validates against URL params |
| Single admin role | One "admin" role for everything | Split: Company Owner, Company Admin, Workspace Admin, Domain Admin |
| Sync job without tenant context | Background job runs without knowing which tenant | Job payload ALWAYS includes full `tenantContext` |
| Webhook without signature | Outgoing webhooks with no verification | HMAC-SHA256 signature on every webhook delivery |

### A05: Security Misconfiguration

**Stack-specific checklist:**

| Component | Misconfiguration Risk | Correct Configuration |
|-----------|----------------------|----------------------|
| NestJS | CORS `origin: '*'` in production | Explicit origin allowlist from env var |
| NestJS | No Helmet.js middleware | `app.use(helmet())` with strict CSP |
| Next.js | Missing security headers | `next.config.js` headers array with CSP, X-Frame-Options, etc. |
| PostgreSQL | Default `postgres` superuser for app | Dedicated app user with minimum grants (SELECT, INSERT, UPDATE on app tables only) |
| Redis | No AUTH, no TLS, bound to 0.0.0.0 | AUTH required, TLS in production, bound to internal network |
| Docker | Running as root, all capabilities | `USER node`, drop all capabilities, read-only filesystem where possible |
| BullMQ | Bull Board exposed publicly | Bull Board behind AdminJwtGuard + VPN only |
| Sentry | PII in error reports | Configure `beforeSend` to strip PII fields |

### A06: Vulnerable and Outdated Components

| Practice | Implementation |
|----------|---------------|
| Dependency scanning | `npm audit` in CI, fail on high/critical |
| Lock file integrity | `npm ci` (not `npm install`), lockfile committed |
| Automated updates | Dependabot or Renovate with auto-merge for patch versions |
| License compliance | `license-checker` in CI, deny GPL in commercial product |
| Container scanning | Trivy or Snyk on Docker images in CI pipeline |
| Runtime patching | Node.js LTS releases applied within 2 weeks of release |

### A07: Identification and Authentication Failures

> Full patterns in `auth-reference.md`

**Key rules for this stack:**

| Concern | Rule |
|---------|------|
| Password storage | bcrypt cost 12+ or Argon2id — NEVER SHA-256, MD5, or plain text |
| JWT expiry | Access: 15 minutes. Refresh: 7 days. Never indefinite. |
| Token storage (frontend) | HttpOnly Secure SameSite=Strict cookie — NEVER localStorage |
| MFA for admin | AdminMfaGuard on all `/admin/*` routes — TOTP or WebAuthn |
| Account lockout | Lock after 5 failed attempts for 15 minutes — exponential backoff |
| Session invalidation | On password change: invalidate ALL sessions. On role change: invalidate affected sessions. |
| SSO security | Validate SAML assertions: audience, recipient, timestamps. Validate OAuth state parameter. |
| Impersonation | Max 1 hour, non-renewable, reason required, every action logged as `admin_impersonation` |

### A08: Software and Data Integrity Failures

| Concern | Control |
|---------|---------|
| CI/CD pipeline | Branch protection: require PR approval + passing checks before merge to main |
| Dependency integrity | `package-lock.json` committed, `npm ci` verifies hashes |
| Webhook verification | Incoming webhooks: verify HMAC signature. Outgoing: sign with per-tenant secret. |
| Migration integrity | Migrations in version control, checksummed, applied in order |
| Container provenance | Pin base images by digest, not tag. Rebuild on security advisory. |
| Subresource integrity | CDN assets use SRI hashes in `<script>` and `<link>` tags |

### A09: Security Logging and Monitoring Failures

**What MUST be logged (security events):**

| Event | Log Level | Required Fields |
|-------|-----------|----------------|
| Login success | INFO | userId, method (password/SSO/MFA), IP, userAgent |
| Login failure | WARN | attemptedEmail, method, IP, userAgent, failureReason |
| Token refresh | INFO | userId, oldTokenExp, newTokenExp |
| Permission denied (403) | WARN | userId, resource, action, requiredPermission |
| Cross-tenant access attempt | ERROR | userId, ownTenantId, targetTenantId, resource |
| Admin impersonation start | WARN | adminId, targetUserId, reason, expiresAt |
| Admin impersonation end | INFO | adminId, targetUserId, duration, actionsPerformed |
| Password change | INFO | userId, changedBy (self or admin) |
| Role/permission change | WARN | userId, changedBy, oldRole, newRole |
| Bulk data export | WARN | userId, exportType, recordCount, tenantScope |
| API key created/revoked | WARN | userId, keyPrefix (last 4), scope |
| Suspicious activity | ERROR | userId, activityType, details, automated=true |

**Log format (Pino structured logging):**

```typescript
// Security event logger — separate from application logger
const securityLogger = pino({
  name: 'security',
  level: 'info',
  redact: {
    paths: ['password', 'token', 'refreshToken', 'apiKey', 'ssn', 'creditCard'],
    censor: '[REDACTED]',
  },
});

// Usage in auth service
securityLogger.warn({
  event: 'login_failure',
  email: dto.email,
  ip: request.ip,
  userAgent: request.headers['user-agent'],
  reason: 'invalid_password',
  attemptCount: lockoutInfo.attempts,
});
```

**Alert thresholds:**

| Condition | Action |
|-----------|--------|
| >10 failed logins from same IP in 5min | Rate limit + alert |
| >5 cross-tenant access attempts by same user | Block user + page on-call |
| Admin impersonation > 30 min active | Alert admin's manager |
| Bulk export > 10k records | Alert security team |
| New API key for service account | Alert workspace admin |

### A10: Server-Side Request Forgery (SSRF)

**Where SSRF risk exists in this stack:**

| Feature | SSRF Vector | Defense |
|---------|-------------|---------|
| Webhook delivery | User provides callback URL | Allowlist check + deny private IPs + timeout (5s) |
| File import from URL | User provides file URL for import | Allowlist domains + validate content-type + size limit |
| SSO metadata discovery | SAML IdP metadata URL | Only fetch from configured, admin-approved URLs |
| Email template preview | Template references external images | Proxy through image CDN, never fetch server-side |
| Link tracking | Redirect URL in tracking pixel | Validate URL schema (https only), deny private networks |

**SSRF prevention utility:**

```typescript
import { URL } from 'url';
import { lookup } from 'dns/promises';

const PRIVATE_RANGES = [
  /^127\./,           // Loopback
  /^10\./,            // Class A private
  /^172\.(1[6-9]|2\d|3[01])\./,  // Class B private
  /^192\.168\./,      // Class C private
  /^169\.254\./,      // Link-local
  /^0\./,             // Current network
  /^::1$/,            // IPv6 loopback
  /^fc00:/,           // IPv6 private
  /^fe80:/,           // IPv6 link-local
];

export async function validateOutboundUrl(url: string): Promise<boolean> {
  const parsed = new URL(url);

  // Only allow HTTPS
  if (parsed.protocol !== 'https:') return false;

  // Resolve DNS to check for SSRF via DNS rebinding
  const { address } = await lookup(parsed.hostname);
  if (PRIVATE_RANGES.some(range => range.test(address))) return false;

  return true;
}
```

---

## PHASE FLOW — APPLY TO EVERY SECURITY DECISION

### Phase 1: Threat Modeling (Before Writing Code)

For every new feature or significant change:

**1.1 — Identify assets and actors:**

```
ASSETS:     What data does this feature touch? (PII, credentials, billing, tenant data)
ACTORS:     Who interacts? (end user, workspace admin, company admin, system/worker, external API)
ENTRY POINTS: HTTP endpoint? WebSocket? SSE? BullMQ job? Cron? Webhook?
TRUST BOUNDARIES: Does this cross tenant boundaries? Auth boundaries? Network boundaries?
```

**1.2 — STRIDE analysis (per entry point):**

| Threat | Question | Example |
|--------|----------|---------|
| **S**poofing | Can an attacker pretend to be someone else? | Forge JWT, replay session, steal API key |
| **T**ampering | Can an attacker modify data in transit or at rest? | Modify request body, tamper with cache, alter job payload |
| **R**epudiation | Can an actor deny performing an action? | Missing audit log, unsigned webhook, no timestamp |
| **I**nformation Disclosure | Can data leak to unauthorized parties? | Error messages with stack traces, cache without tenant scope, verbose logging |
| **D**enial of Service | Can an attacker make the service unavailable? | Unbounded query, recursive import, queue flooding |
| **E**levation of Privilege | Can a user gain higher permissions? | Workspace admin to company admin, user to impersonation, public to authenticated |

> Full STRIDE analysis templates for each component in `threat-model-reference.md`

### Phase 2: Authentication Design

> Full implementation patterns in `auth-reference.md`

**Decision matrix — which auth method for which context:**

| Context | Method | Token Type | Storage |
|---------|--------|-----------|---------|
| Web app (browser) | Better Auth session | JWT (access) + Opaque (refresh) | HttpOnly Secure cookie |
| Mobile app | OAuth2 PKCE | JWT (access) + Opaque (refresh) | Secure storage (Keychain/Keystore) |
| API integration | API key | Opaque key with scope | Server-side hash, client stores plaintext |
| Service-to-service | mTLS or signed JWT | Short-lived JWT | Certificate store |
| Admin panel | Session + MFA (TOTP/WebAuthn) | JWT with `mfa: true` claim | HttpOnly Secure cookie |
| Impersonation | Time-limited token | JWT with `impersonator` claim | HttpOnly Secure cookie (replaces user session) |
| Webhook delivery | HMAC signature | N/A (signature in header) | Shared secret per tenant |

### Phase 3: Authorization Design

**Three layers of authorization (ALL must pass):**

```
Layer 1: ROUTE GUARD (NestJS guard)
  - Is the user authenticated?
  - Does the user have the required role for this route?
  - Is the endpoint public (@Public) or protected (default)?

Layer 2: TENANT CONTEXT (TenantContextGuard)
  - Does the user belong to the requested workspace?
  - Does the user's company own the requested domain?
  - Is the subscription active (not expired/suspended)?

Layer 3: ABILITY CHECK (CASL)
  - Can this specific user perform this specific action on this specific resource?
  - Is the action allowed by their role + workspace membership + custom permissions?
  - Are field-level restrictions applied? (e.g., user can read but not update salary field)
```

**CASL ability definition pattern:**

```typescript
// abilities/ability.factory.ts
type Actions = 'create' | 'read' | 'update' | 'delete' | 'manage' | 'export' | 'impersonate';
type Subjects = 'Recipient' | 'Campaign' | 'Training' | 'Settings' | 'User' | 'Workspace' | 'all';

export function defineAbilitiesFor(user: AuthenticatedUser, tenantContext: DomainContext) {
  const { can, cannot, build } = new AbilityBuilder<Ability<[Actions, Subjects]>>(Ability);

  switch (user.role) {
    case 'company_owner':
      can('manage', 'all');  // Full access within company
      break;

    case 'company_admin':
      can('manage', 'all');
      cannot('delete', 'Workspace');  // Only owner can delete workspaces
      cannot('manage', 'User', { role: 'company_owner' });  // Cannot modify owner
      break;

    case 'workspace_admin':
      can('manage', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Campaign', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Training', { workspaceId: tenantContext.workspaceId });
      can('manage', 'Settings', { workspaceId: tenantContext.workspaceId });
      can('read', 'User', { workspaceId: tenantContext.workspaceId });
      can('create', 'User', { workspaceId: tenantContext.workspaceId });
      cannot('manage', 'User', { role: { $in: ['company_owner', 'company_admin'] } });
      break;

    case 'user':
      can('read', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('create', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('update', 'Recipient', { workspaceId: tenantContext.workspaceId });
      can('read', 'Campaign', { workspaceId: tenantContext.workspaceId });
      // Cannot delete, export, or manage settings
      break;
  }

  // Subscription enforcement — cannot exceed limits regardless of role
  if (tenantContext.subscriptionStatus !== 'active' && tenantContext.subscriptionStatus !== 'trialing') {
    cannot('create', 'all');
    cannot('update', 'all');
  }

  return build();
}
```

### Phase 4: Input Validation & Sanitization

**Validation layers (ALL must be present):**

```
Layer 1: DTO VALIDATION (NestJS Pipe)
  - class-validator decorators on DTO class
  - Whitelist enabled (strip unknown properties)
  - Transform enabled (type coercion)

Layer 2: BUSINESS VALIDATION (Service)
  - Uniqueness checks (scoped per domain)
  - Referential integrity (FK exists in same tenant)
  - Business rule constraints (limit checks, status transitions)

Layer 3: DATABASE CONSTRAINTS
  - NOT NULL on required columns
  - CHECK constraints for enum values
  - UNIQUE constraints scoped per tenant
  - FK constraints with appropriate ON DELETE
```

**NestJS global validation setup:**

```typescript
// main.ts — MUST be configured globally
app.useGlobalPipes(new ValidationPipe({
  whitelist: true,           // Strip properties not in DTO
  forbidNonWhitelisted: true, // Throw on unknown properties
  transform: true,            // Auto-transform types
  transformOptions: {
    enableImplicitConversion: false,  // Require explicit @Type() decorators
  },
  exceptionFactory: (errors) => {
    // Return safe error messages — no internal details
    const messages = errors.map(e =>
      Object.values(e.constraints ?? {}).join(', ')
    );
    return new BadRequestException({ message: 'Validation failed', errors: messages });
  },
}));
```

**DTO example with security-relevant validation:**

```typescript
export class CreateRecipientDto {
  @IsEmail()
  @MaxLength(254)           // RFC 5321 max email length
  @Transform(({ value }) => value?.toLowerCase().trim())
  email: string;

  @IsString()
  @MinLength(1)
  @MaxLength(100)
  @Matches(/^[a-zA-Z\s\-'.]+$/)  // Prevent injection in name fields
  firstName: string;

  @IsString()
  @MinLength(1)
  @MaxLength(100)
  @Matches(/^[a-zA-Z\s\-'.]+$/)
  lastName: string;

  @IsOptional()
  @IsObject()
  @ValidateNested()
  customFields?: Record<string, unknown>;  // Validated against workspace field definitions in service
}
```

### Phase 5: Data Protection & Privacy

**PII inventory for this platform:**

| Data | Classification | Storage Rule | Access Rule | Retention |
|------|---------------|-------------|-------------|-----------|
| Email address | PII | Encrypted at rest (column-level for regulated tenants) | Workspace members only | Until recipient deletion + 30d grace |
| First/last name | PII | Standard storage | Workspace members only | Until recipient deletion + 30d grace |
| Phone number | PII | Encrypted at rest | Workspace members only | Until recipient deletion + 30d grace |
| IP address (login) | PII | Audit log (append-only) | Security team + admin | 90 days |
| Password hash | Secret | bcrypt/Argon2id | System only (never returned via API) | Until changed |
| SSO tokens | Secret | Encrypted at rest | System only | Session duration |
| Billing info | PCI-adjacent | Stored by payment provider (Stripe), only reference ID in our DB | Company Admin | Per payment provider policy |
| Audit logs | Compliance | Append-only, integrity-hashed | Company Admin + Security team | Configurable (default: 1 year) |
| Email content (campaigns) | Business confidential | Standard storage | Workspace members | Until campaign deletion + 30d |
| Training results | HR-sensitive | Standard storage | Workspace Admin + Company Admin | Configurable per compliance requirement |

**Data access rules by role:**

| Role | Own Workspace Data | Other Workspace Data | Cross-Company | PII Export |
|------|-------------------|---------------------|--------------|-----------|
| User | Read + Write (scoped) | None | None | None |
| Workspace Admin | Full CRUD | None | None | With audit log |
| Company Admin | Read all | Read all (own company) | None | With audit log + approval |
| Company Owner | Full CRUD all | Full CRUD all (own company) | None | With audit log |
| Platform Admin (internal) | Read via impersonation | Read via impersonation | Read-only (audit trail) | Requires ticket + manager approval |

### Phase 6: Security Testing

**Required security tests per feature:**

| Test Type | What It Covers | When to Run |
|-----------|---------------|-------------|
| Tenant isolation test | Cross-workspace data leak prevention | Every module, every PR |
| Auth bypass test | Unauthenticated access to protected endpoints | Every new endpoint |
| IDOR test | Accessing resources by guessing IDs | Every resource endpoint |
| Input validation test | Malicious input handling (SQL injection, XSS payloads) | Every input endpoint |
| Rate limit test | Verify rate limits work under load | Auth endpoints, bulk operations |
| Permission escalation test | Role boundary enforcement | Every role-restricted operation |
| Session management test | Token expiry, refresh, invalidation | Auth module changes |

**Negative security test patterns:**

```typescript
describe('Security: Cross-Tenant Isolation', () => {
  it('workspace admin cannot access another workspace recipients', async () => {
    const wsA = await createWorkspace(companyId);
    const wsB = await createWorkspace(companyId);
    const recipient = await createRecipient(wsA);

    await expect(
      service.findById(recipient.id, wsB.tenantContext)
    ).rejects.toThrow(ForbiddenException);
  });

  it('domain query cannot return data from sibling domain', async () => {
    const domainA = await createDomain(workspaceId);
    const domainB = await createDomain(workspaceId);
    const recipient = await createRecipient(domainA);

    const results = await repo.findAll(domainB.id);
    expect(results.map(r => r.id)).not.toContain(recipient.id);
  });

  it('cache key collision across tenants returns no data', async () => {
    await cacheService.set('recipients:list', data, wsA.tenantContext);
    const cached = await cacheService.get('recipients:list', wsB.tenantContext);
    expect(cached).toBeNull();  // Different tenant scope = cache miss
  });
});

describe('Security: Authorization Boundaries', () => {
  it('user role cannot delete recipients', async () => {
    const user = await createUser({ role: 'user' });
    await expect(
      service.delete(recipientId, user.tenantContext)
    ).rejects.toThrow(ForbiddenException);
  });

  it('workspace admin cannot modify company-level settings', async () => {
    const wsAdmin = await createUser({ role: 'workspace_admin' });
    await expect(
      settingsService.updateCompanySettings(dto, wsAdmin.tenantContext)
    ).rejects.toThrow(ForbiddenException);
  });

  it('expired subscription blocks mutations', async () => {
    const ctx = await createTenantContext({ subscriptionStatus: 'expired' });
    await expect(
      service.create(dto, ctx)
    ).rejects.toThrow(PaymentRequiredException);
  });
});

describe('Security: Input Validation', () => {
  it('rejects SQL injection in search parameter', async () => {
    const malicious = "'; DROP TABLE recipients; --";
    const result = await service.search(malicious, tenantContext);
    expect(result).toEqual([]);  // Safe — no error, no injection
  });

  it('rejects XSS in custom field value', async () => {
    const xssPayload = '<script>alert("xss")</script>';
    const dto = { customFields: { bio: xssPayload } };
    const result = await service.create(dto, tenantContext);
    expect(result.customFields.bio).not.toContain('<script>');
  });

  it('rejects oversized request body', async () => {
    const hugePayload = { data: 'x'.repeat(10_000_000) };
    await expect(
      controller.create(hugePayload)
    ).rejects.toThrow(PayloadTooLargeException);
  });
});
```

### Phase 7: Incident Response

**Security incident classification:**

| Severity | Definition | Response Time | Examples |
|----------|-----------|---------------|---------|
| P0 — Critical | Active data breach, system compromise | < 15 minutes | Cross-tenant data exposure, credential leak, active exploit |
| P1 — High | Vulnerability with exploitation risk | < 1 hour | Auth bypass found, SQL injection, privilege escalation |
| P2 — Medium | Security deficiency, no active exploit | < 24 hours | Missing rate limit, weak password policy, outdated dependency |
| P3 — Low | Improvement opportunity | Next sprint | Missing security header, verbose error message, audit gap |

**Incident response checklist (P0/P1):**

```
PHASE 1: DETECT & TRIAGE (0-15 min)
  [ ] Confirm the incident is real (not false positive)
  [ ] Classify severity (P0-P3)
  [ ] Identify affected tenants/data
  [ ] Assign incident commander

PHASE 2: CONTAIN (15-60 min)
  [ ] Isolate affected systems (disable feature flag, block IP, revoke token)
  [ ] Preserve evidence (logs, snapshots, memory dumps)
  [ ] Prevent further damage (rotate exposed secrets, invalidate sessions)
  [ ] Notify affected tenants (if data breach confirmed)

PHASE 3: ERADICATE (1-4 hours)
  [ ] Identify root cause
  [ ] Develop and test fix
  [ ] Deploy fix (hotfix branch -> expedited review -> deploy)
  [ ] Verify fix resolves the vulnerability

PHASE 4: RECOVER (4-24 hours)
  [ ] Restore normal operations
  [ ] Monitor for recurrence
  [ ] Verify all affected tenants have clean state
  [ ] Document timeline and actions taken

PHASE 5: POST-MORTEM (within 48 hours)
  [ ] Blameless post-mortem document
  [ ] Root cause analysis (5 Whys)
  [ ] Action items with owners and deadlines
  [ ] Update security controls to prevent recurrence
  [ ] Update threat model if new attack vector identified
```

---

## SECURITY HEADERS (NestJS + Next.js)

### NestJS Security Middleware

```typescript
// main.ts — apply security middleware
import helmet from 'helmet';

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],  // Required for Tailwind
      imgSrc: ["'self'", 'data:', 'https:'],
      connectSrc: ["'self'"],
      fontSrc: ["'self'"],
      objectSrc: ["'none'"],
      frameSrc: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
    },
  },
  crossOriginEmbedderPolicy: true,
  crossOriginOpenerPolicy: true,
  crossOriginResourcePolicy: { policy: 'same-origin' },
  referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
  hsts: { maxAge: 31536000, includeSubDomains: true, preload: true },
  noSniff: true,
  xssFilter: true,    // Legacy X-XSS-Protection
  frameguard: { action: 'deny' },
}));

// CORS — explicit origin allowlist
app.enableCors({
  origin: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000'],
  credentials: true,
  methods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'x-workspace-id', 'x-domain-id'],
  exposedHeaders: ['X-Request-Id'],
  maxAge: 86400,  // 24 hours preflight cache
});

// Request size limit — prevent DoS via large payloads
app.use(json({ limit: '1mb' }));
app.use(urlencoded({ limit: '1mb', extended: true }));
```

### Next.js Security Headers

```typescript
// next.config.ts
const securityHeaders = [
  { key: 'X-DNS-Prefetch-Control', value: 'on' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()' },
];

export default {
  async headers() {
    return [{ source: '/(.*)', headers: securityHeaders }];
  },
};
```

---

## REDIS SECURITY

### Authentication & Network

```yaml
# Production Redis configuration
requirepass: ${REDIS_PASSWORD}        # Strong password (32+ chars)
bind: 127.0.0.1                       # Local only (Docker internal network)
protected-mode: yes
tls-port: 6380                        # TLS for production
tls-cert-file: /etc/redis/tls/cert.pem
tls-key-file: /etc/redis/tls/key.pem
rename-command FLUSHALL ""            # Disable dangerous commands
rename-command FLUSHDB ""
rename-command CONFIG ""              # Prevent runtime config changes
rename-command DEBUG ""
maxmemory-policy: allkeys-lru         # Evict least recently used on memory pressure
```

### Tenant-Scoped Cache Security

```typescript
// EVERY Redis operation MUST include tenant scope in key
// NEVER store or retrieve without tenant prefix

// WRONG — shared key, any tenant can read
await redis.set('recipients:count', count);

// RIGHT — tenant-scoped key
await redis.set(`domain:${domainId}:recipients:count`, count);

// WRONG — cache invalidation misses tenant scope
await redis.del('recipients:*');

// RIGHT — invalidate only affected tenant's cache
await redis.del(`domain:${domainId}:recipients:*`);
```

### Session Security in Redis

```typescript
// Session keys include user ID + device fingerprint
const sessionKey = `session:${userId}:${deviceFingerprint}`;
await redis.setex(sessionKey, SESSION_TTL, JSON.stringify({
  userId,
  workspaceId,
  role,
  isImpersonated: false,
  createdAt: Date.now(),
}));

// On password change — invalidate ALL sessions for user
const keys = await redis.keys(`session:${userId}:*`);
if (keys.length) await redis.del(...keys);
```

---

## BULLMQ WORKER SECURITY

### Job Payload Security

```typescript
// EVERY job MUST include tenantContext — no exceptions
interface SecureJobPayload<T> {
  tenantContext: {
    companyId: string;
    workspaceId: string;
    domainId: string;
    userId: string;         // Who initiated this job
    subscriptionTier: string;
  };
  data: T;
  metadata: {
    createdAt: number;
    correlationId: string;  // For tracing across services
  };
}

// Processor MUST validate tenant context before processing
@Processor('import')
export class ImportProcessor extends BaseProcessor {
  async process(job: Job<SecureJobPayload<ImportData>>) {
    const { tenantContext, data } = job.data;

    // Validate tenant still exists and subscription is active
    const tenant = await this.tenantService.validate(tenantContext);
    if (!tenant.isActive) {
      throw new Error(`Tenant ${tenantContext.companyId} subscription inactive`);
    }

    // Process with validated tenant scope
    await this.importService.execute(data, tenant);
  }
}
```

### Job Queue Abuse Prevention

```typescript
// Rate limit job submission per tenant
const JOB_RATE_LIMITS = {
  import: { max: 5, window: '1h' },       // Max 5 imports per hour per tenant
  'bulk-operations': { max: 10, window: '1h' },
  'email-send': { max: 100, window: '1h' },
};

async function submitJob(queueName: string, payload: SecureJobPayload<unknown>) {
  const key = `job-rate:${queueName}:${payload.tenantContext.companyId}`;
  const limit = JOB_RATE_LIMITS[queueName];

  const current = await redis.incr(key);
  if (current === 1) await redis.expire(key, parseDuration(limit.window));
  if (current > limit.max) {
    throw new TooManyRequestsException(
      `Rate limit: max ${limit.max} ${queueName} jobs per ${limit.window}`
    );
  }

  await queue.add(queueName, payload, {
    jobId: `${queueName}:${payload.tenantContext.domainId}:${Date.now()}`,
    attempts: 3,
    backoff: { type: 'exponential', delay: 5000 },
  });
}
```

---

## MASTER CHECKLIST — Run Before Shipping ANY Feature

### Authentication & Session (8 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | JWT access token expiry <= 15 minutes | CRITICAL |
| 2 | Refresh token stored in HttpOnly Secure SameSite cookie | BLOCKER |
| 3 | Password hashed with bcrypt (cost 12+) or Argon2id | BLOCKER |
| 4 | Account lockout after 5 failed attempts | CRITICAL |
| 5 | All sessions invalidated on password change | CRITICAL |
| 6 | MFA required for admin routes (AdminMfaGuard) | CRITICAL |
| 7 | Impersonation: 1hr max, non-renewable, reason required, fully audited | CRITICAL |
| 8 | SSO assertions validated: audience, recipient, timestamps, signature | CRITICAL |

### Authorization & Access Control (10 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | TenantContextGuard on EVERY protected route | BLOCKER |
| 2 | CASL ability check in service layer (not just route guard) | CRITICAL |
| 3 | domainId in WHERE clause on every data query | BLOCKER |
| 4 | workspaceId validated against JWT claims (not trusted from header alone) | BLOCKER |
| 5 | Company Admin write operations require explicit workspaceId | CRITICAL |
| 6 | Subscription status checked before mutations | CRITICAL |
| 7 | @Public decorator only on genuinely public routes (health, auth) | BLOCKER |
| 8 | No ambient authority (every operation requires explicit context) | CRITICAL |
| 9 | Field-level permissions enforced for sensitive fields | MAJOR |
| 10 | Cross-workspace isolation test exists for this module | BLOCKER |

### Input Validation & Injection Prevention (8 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | DTO with class-validator on every endpoint body | CRITICAL |
| 2 | `whitelist: true` + `forbidNonWhitelisted: true` in ValidationPipe | CRITICAL |
| 3 | No raw SQL string concatenation (Drizzle query builder or parameterized) | BLOCKER |
| 4 | HTML content sanitized with DOMPurify before storage | CRITICAL |
| 5 | File upload: type validation, size limit (10MB default), content scanning | CRITICAL |
| 6 | URL inputs validated against SSRF (no private IPs, HTTPS only) | CRITICAL |
| 7 | Request body size limited (1MB default) | MAJOR |
| 8 | Custom field values validated against workspace field definitions | MAJOR |

### Data Protection & Privacy (6 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | PII fields encrypted at rest for regulated tenants | CRITICAL |
| 2 | Passwords never returned in any API response | BLOCKER |
| 3 | API keys show only last 4 chars in UI | CRITICAL |
| 4 | Error responses do not leak stack traces, SQL, or internal paths | CRITICAL |
| 5 | Logs redact PII (password, token, SSN, credit card) | CRITICAL |
| 6 | Bulk export logged with record count and tenant scope | MAJOR |

### Infrastructure & Headers (6 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | Helmet.js configured with strict CSP | CRITICAL |
| 2 | CORS origin allowlist (no wildcard in production) | CRITICAL |
| 3 | HSTS enabled with includeSubDomains and preload | MAJOR |
| 4 | Redis keys include tenant scope | BLOCKER |
| 5 | Docker containers run as non-root | CRITICAL |
| 6 | No secrets in Docker image layers or git history | BLOCKER |

### Monitoring & Incident Response (6 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | Security events logged (auth, permission denied, cross-tenant attempts) | CRITICAL |
| 2 | PII redacted from logs | CRITICAL |
| 3 | Alert on >10 failed logins from same IP in 5min | MAJOR |
| 4 | Alert on cross-tenant access attempts | CRITICAL |
| 5 | Audit log for every mutation (@Audit decorator) | CRITICAL |
| 6 | Incident response runbook exists and team knows location | MAJOR |

### Dependencies & Supply Chain (4 items)

| # | Check | Severity |
|---|-------|----------|
| 1 | `npm audit` runs in CI, fails on high/critical | CRITICAL |
| 2 | Lock file committed, `npm ci` used (not `npm install`) | MAJOR |
| 3 | Base Docker images pinned by digest | MAJOR |
| 4 | No GPL dependencies in commercial codebase | MAJOR |
