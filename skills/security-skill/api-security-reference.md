# API Security Reference — Rate Limiting, Input Validation, CORS/CSP, File Uploads, Webhooks, Abuse Prevention

> Read this file when implementing rate limiting, input validation, CORS/CSP headers, file upload security,
> webhook signing/verification, API abuse prevention, or secure error handling. All patterns are for
> NestJS + Next.js 16 + PostgreSQL + Redis + BullMQ in a multi-tenant SaaS context.

---

## Table of Contents
1. [Rate Limiting Architecture](#rate-limiting-architecture)
2. [Input Validation Patterns](#input-validation-patterns)
3. [CORS & CSP Configuration](#cors--csp-configuration)
4. [File Upload Security](#file-upload-security)
5. [Webhook Security](#webhook-security)
6. [API Abuse Prevention](#api-abuse-prevention)
7. [Error Handling Security](#error-handling-security)

---

## Rate Limiting Architecture

Four layers, each independent. A request must pass all four. Redis-backed for distributed consistency.

### Layer Summary

| Layer | Scope | Budget | Purpose |
|-------|-------|--------|---------|
| 1 — Global | Per IP address | 300 req/min | DDoS / brute force baseline |
| 2 — Tenant | Per companyId | 1000 req/min | Noisy neighbor prevention |
| 3 — Endpoint | Per route class | Varies (see table) | Protect sensitive endpoints |
| 4 — Operation | Per operation type | Varies (see table) | Bulk ops, imports, exports |

### Layer 1: Global Rate Limit (Per-IP)

Applied at the reverse proxy or gateway before reaching NestJS.

| Setting | Value | Rationale |
|---------|-------|-----------|
| Window | 1 minute (sliding) | Short window catches bursts |
| Limit | 300 requests | Generous for normal use, blocks scripted abuse |
| Key | Client IP (from trusted proxy `X-Forwarded-For`) | Never trust raw `X-Forwarded-For` — configure trusted proxy count |
| Response | 429 + `Retry-After` header | Clear feedback for legitimate clients |

```typescript
// NestJS ThrottlerModule — global rate limit
import { ThrottlerModule, ThrottlerGuard } from '@nestjs/throttler';
import { ThrottlerStorageRedisService } from '@nest-lab/throttler-storage-redis';

@Module({
  imports: [
    ThrottlerModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        throttlers: [
          {
            name: 'global',
            ttl: 60000,   // 1 minute window
            limit: 300,   // 300 requests per window
          },
        ],
        storage: new ThrottlerStorageRedisService(config.get('REDIS_URL')),
      }),
    }),
  ],
  providers: [
    {
      provide: APP_GUARD,
      useClass: ThrottlerGuard,
    },
  ],
})
export class AppModule {}
```

### Layer 2: Per-Tenant Rate Limit

Prevents a single tenant from consuming disproportionate resources. Keyed on `companyId` from JWT claims (not client-provided headers).

| Plan | Limit (req/min) | Burst Allowance |
|------|-----------------|-----------------|
| Free | 200 | None |
| Pro | 500 | 100 extra for 10s burst |
| Business | 1000 | 200 extra for 10s burst |
| Enterprise | 5000 | Custom (negotiated) |

```typescript
// Custom tenant-scoped throttler guard
@Injectable()
export class TenantThrottlerGuard extends ThrottlerGuard {
  private readonly PLAN_LIMITS: Record<string, number> = {
    free: 200,
    pro: 500,
    business: 1000,
    enterprise: 5000,
  };

  protected async getTracker(req: Request): Promise<string> {
    // Key by companyId from JWT — not IP, not header
    const user = req['user'] as AccessTokenPayload;
    if (!user?.companyId) {
      return req.ip; // fallback for unauthenticated requests
    }
    return `tenant:${user.companyId}`;
  }

  protected async getLimit(context: ExecutionContext): Promise<number> {
    const req = context.switchToHttp().getRequest();
    const user = req['user'] as AccessTokenPayload;
    return this.PLAN_LIMITS[user?.tier ?? 'free'] ?? 200;
  }
}
```

### Layer 3: Per-Endpoint Rate Limit

Different endpoint categories have different budgets.

| Endpoint Category | Limit | Window | Rationale |
|-------------------|-------|--------|-----------|
| `POST /auth/login` | 5 | 15 min | Brute force prevention |
| `POST /auth/forgot-password` | 3 | 1 hour | Abuse prevention |
| `POST /auth/register` | 10 | 1 hour | Registration spam |
| `POST /auth/refresh` | 30 | 15 min | Legitimate multi-tab use |
| `GET /*/recipients` (list) | 60 | 1 min | Scraping prevention |
| `POST /*/recipients` (create) | 30 | 1 min | Spam prevention |
| `POST /*/imports/*` | 5 | 1 hour | Resource-heavy |
| `POST /*/exports` | 10 | 1 hour | Data exfil prevention |
| `GET /*/progress` (SSE) | 10 | 1 min | Connection limit |

```typescript
// Per-endpoint rate limit decorator
import { Throttle, SkipThrottle } from '@nestjs/throttler';

@Controller('auth')
export class AuthController {
  @Post('login')
  @Throttle({ default: { limit: 5, ttl: 900000 } }) // 5 per 15 min
  async login(@Body() dto: LoginDto) { /* ... */ }

  @Post('forgot-password')
  @Throttle({ default: { limit: 3, ttl: 3600000 } }) // 3 per hour
  async forgotPassword(@Body() dto: ForgotPasswordDto) { /* ... */ }

  @Post('refresh')
  @Throttle({ default: { limit: 30, ttl: 900000 } }) // 30 per 15 min
  async refresh(@Req() req: Request) { /* ... */ }
}

@Controller('domains/:domainId/recipients')
export class RecipientsController {
  @Get()
  @Throttle({ default: { limit: 60, ttl: 60000 } }) // 60 per min
  findAll() { /* ... */ }

  @Post('imports/upload-url')
  @Throttle({ default: { limit: 5, ttl: 3600000 } }) // 5 per hour
  createImport() { /* ... */ }
}
```

### Layer 4: Per-Operation Rate Limit (Bulk Operations)

Separate budget for expensive operations. These do NOT share quota with regular API calls.

| Operation | Limit | Window | Key |
|-----------|-------|--------|-----|
| CSV/Excel Import | 5 jobs | 1 hour | `op-rate:import:{companyId}` |
| Bulk Update (>100 rows) | 10 jobs | 1 hour | `op-rate:bulk-update:{companyId}` |
| Data Export | 10 exports | 1 hour | `op-rate:export:{companyId}` |
| Bulk Delete | 5 jobs | 1 hour | `op-rate:bulk-delete:{companyId}` |
| Webhook Test Delivery | 20 tests | 1 hour | `op-rate:webhook-test:{workspaceId}` |

```typescript
@Injectable()
export class OperationRateLimitService {
  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  async checkAndIncrement(
    operation: string,
    tenantKey: string,
    limit: number,
    windowSeconds: number,
  ): Promise<void> {
    const key = `op-rate:${operation}:${tenantKey}`;
    const current = await this.redis.incr(key);
    if (current === 1) {
      await this.redis.expire(key, windowSeconds);
    }
    if (current > limit) {
      const ttl = await this.redis.ttl(key);
      throw new TooManyRequestsException({
        message: `Rate limit exceeded for ${operation}: max ${limit} per ${windowSeconds}s`,
        retryAfter: ttl,
      });
    }
  }
}
```

### Rate Limit Response Headers

All rate-limited responses MUST include these headers.

| Header | Value | Purpose |
|--------|-------|---------|
| `X-RateLimit-Limit` | Max requests in current window | Client knows their budget |
| `X-RateLimit-Remaining` | Requests left in current window | Client can pace requests |
| `X-RateLimit-Reset` | Unix timestamp when window resets | Client knows when to retry |
| `Retry-After` | Seconds until next allowed request (on 429 only) | Standard HTTP retry hint |

```typescript
// Interceptor to add rate limit headers to every response
@Injectable()
export class RateLimitHeadersInterceptor implements NestInterceptor {
  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  async intercept(context: ExecutionContext, next: CallHandler): Promise<Observable<any>> {
    const req = context.switchToHttp().getRequest();
    const res = context.switchToHttp().getResponse();
    const user = req['user'] as AccessTokenPayload;

    if (user?.companyId) {
      const key = `throttle:tenant:${user.companyId}`;
      const [current, ttl] = await Promise.all([
        this.redis.get(key),
        this.redis.ttl(key),
      ]);
      const limit = this.getPlanLimit(user.tier);
      const remaining = Math.max(0, limit - parseInt(current ?? '0', 10));

      res.setHeader('X-RateLimit-Limit', limit);
      res.setHeader('X-RateLimit-Remaining', remaining);
      res.setHeader('X-RateLimit-Reset', Math.floor(Date.now() / 1000) + Math.max(ttl, 0));
    }

    return next.handle();
  }

  private getPlanLimit(tier: string): number {
    const limits: Record<string, number> = { free: 200, pro: 500, business: 1000, enterprise: 5000 };
    return limits[tier] ?? 200;
  }
}
```

### 429 Response Format

```json
{
  "statusCode": 429,
  "error": "Too Many Requests",
  "message": "Rate limit exceeded. Please retry after the specified time.",
  "retryAfter": 42
}
```

Never silently drop requests. Always return 429 with `Retry-After`. Clients depend on this for backoff logic.

---

## Input Validation Patterns

### class-validator Decorator Quick Reference

| Decorator | Use For | Example |
|-----------|---------|---------|
| `@IsString()` | String fields | Names, descriptions |
| `@IsEmail()` | Email addresses | `@IsEmail() email: string` |
| `@IsUUID('4')` | UUID v4 identifiers | Domain IDs, workspace IDs |
| `@IsInt()` / `@IsNumber()` | Numeric fields | Counts, limits |
| `@Min(n)` / `@Max(n)` | Numeric bounds | `@Min(1) @Max(100) limit: number` |
| `@MinLength(n)` / `@MaxLength(n)` | String length | `@MinLength(1) @MaxLength(100) name: string` |
| `@Matches(regex)` | Pattern match | `@Matches(/^[a-zA-Z\s\-'.]+$/) name: string` |
| `@IsEnum(Enum)` | Enum values | `@IsEnum(SortOrder) order: SortOrder` |
| `@IsOptional()` | Optional fields | Stack with other decorators |
| `@IsArray()` | Array fields | Bulk operations |
| `@ArrayMaxSize(n)` | Array size limit | `@ArrayMaxSize(1000) ids: string[]` |
| `@ValidateNested()` | Nested objects | Custom fields, filters |
| `@Type(() => Class)` | Type transformation | Required with `@ValidateNested()` |
| `@IsISO8601()` | Date strings | `@IsISO8601() startDate: string` |
| `@IsUrl()` | URL fields | Webhook URLs |
| `@IsBooleanString()` | Query boolean | `?active=true` |

### Custom Validators for Multi-Tenant Context

```typescript
// Validates that domainId belongs to the user's workspace
@ValidatorConstraint({ name: 'isDomainInWorkspace', async: true })
@Injectable()
export class IsDomainInWorkspaceConstraint implements ValidatorConstraintInterface {
  constructor(private readonly domainRepo: DomainRepository) {}

  async validate(domainId: string, args: ValidationArguments): Promise<boolean> {
    const object = args.object as any;
    const workspaceId = object.workspaceId; // resolved from JWT, not client
    if (!workspaceId || !domainId) return false;

    const domain = await this.domainRepo.findById(domainId);
    return domain?.workspaceId === workspaceId;
  }

  defaultMessage(): string {
    return 'Domain does not belong to your workspace';
  }
}

export function IsDomainInWorkspace(validationOptions?: ValidationOptions) {
  return function (object: object, propertyName: string) {
    registerDecorator({
      target: object.constructor,
      propertyName,
      options: validationOptions,
      constraints: [],
      validator: IsDomainInWorkspaceConstraint,
    });
  };
}

// Usage in DTO:
export class MoveRecipientDto {
  @IsUUID('4')
  @IsDomainInWorkspace()
  targetDomainId: string;
}
```

### Pagination DTO (Secure)

```typescript
export enum SortOrder {
  ASC = 'asc',
  DESC = 'desc',
}

export class PaginationDto {
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100) // HARD LIMIT — never allow unlimited page size
  limit: number = 50;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  @Max(10000) // Prevent deep pagination (use cursor for large datasets)
  offset: number = 0;

  @IsOptional()
  @IsString()
  @MaxLength(50)
  @Matches(/^[a-zA-Z_]+$/) // ONLY allow alphanumeric + underscore for column names
  sortBy: string = 'createdAt';

  @IsOptional()
  @IsEnum(SortOrder)
  sortOrder: SortOrder = SortOrder.DESC;

  @IsOptional()
  @IsString()
  @MaxLength(200) // Prevent oversized search terms
  search?: string;
}
```

**Why `@Matches(/^[a-zA-Z_]+$/)` on sortBy?** Prevents ORDER BY injection. User cannot pass `createdAt; DROP TABLE recipients` as a sort column.

### Cursor-Based Pagination (For Large Datasets)

Offset pagination leaks total count and allows deep enumeration. Use cursor pagination for lists exceeding 10,000 items.

```typescript
export class CursorPaginationDto {
  @IsOptional()
  @IsString()
  @MaxLength(200)
  cursor?: string; // opaque base64-encoded cursor

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit: number = 50;
}

// Cursor encodes: { id: string, createdAt: string }
// Signed with HMAC to prevent tampering
@Injectable()
export class CursorService {
  constructor(@Inject('CURSOR_SECRET') private readonly secret: string) {}

  encode(data: { id: string; createdAt: Date }): string {
    const payload = JSON.stringify({ id: data.id, ts: data.createdAt.toISOString() });
    const signature = createHmac('sha256', this.secret).update(payload).digest('hex');
    return Buffer.from(`${payload}.${signature}`).toString('base64url');
  }

  decode(cursor: string): { id: string; createdAt: Date } | null {
    try {
      const decoded = Buffer.from(cursor, 'base64url').toString();
      const [payload, signature] = decoded.split(/\.(?=[^.]+$)/);
      const expected = createHmac('sha256', this.secret).update(payload).digest('hex');
      if (!timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return null;

      const data = JSON.parse(payload);
      return { id: data.id, createdAt: new Date(data.ts) };
    } catch {
      return null;
    }
  }
}
```

### Sort Column Allowlist (Prevents ORDER BY Injection)

```typescript
// Never pass user input directly to ORDER BY
// Use an allowlist to map front-end column names to DB columns
const ALLOWED_SORT_COLUMNS: Record<string, keyof typeof recipients> = {
  createdAt: 'createdAt',
  updatedAt: 'updatedAt',
  email: 'email',
  firstName: 'firstName',
  lastName: 'lastName',
  status: 'status',
};

function resolveSortColumn(input: string): SQL | null {
  const column = ALLOWED_SORT_COLUMNS[input];
  if (!column) return null; // reject unknown columns — do NOT default
  return recipients[column];
}

// In repository:
async findAll(ctx: DomainContext, pagination: PaginationDto) {
  const sortColumn = resolveSortColumn(pagination.sortBy);
  if (!sortColumn) throw new BadRequestException(`Invalid sort column: ${pagination.sortBy}`);

  return this.db.select()
    .from(recipients)
    .where(eq(recipients.domainId, ctx.domainId))
    .orderBy(pagination.sortOrder === 'asc' ? asc(sortColumn) : desc(sortColumn))
    .limit(pagination.limit)
    .offset(pagination.offset);
}
```

### File Path Traversal Prevention

For file import features where filenames come from user input.

```typescript
import { basename, normalize, resolve } from 'path';

function sanitizeFilename(rawFilename: string): string {
  // 1. Strip path components — take only the filename
  let safe = basename(rawFilename);

  // 2. Normalize Unicode (NFC) to prevent homoglyph attacks
  safe = safe.normalize('NFC');

  // 3. Remove path traversal characters
  safe = safe.replace(/\.\./g, '').replace(/[/\\]/g, '');

  // 4. Remove null bytes (used to truncate filenames in some systems)
  safe = safe.replace(/\0/g, '');

  // 5. Replace non-alphanumeric characters except . - _
  safe = safe.replace(/[^a-zA-Z0-9.\-_]/g, '_');

  // 6. Limit length (255 bytes max for most filesystems)
  if (safe.length > 200) {
    const ext = safe.split('.').pop() ?? '';
    safe = safe.substring(0, 200 - ext.length - 1) + '.' + ext;
  }

  // 7. Ensure the result doesn't start with a dot (hidden files)
  if (safe.startsWith('.')) safe = '_' + safe;

  return safe;
}

// Validate resolved path stays within allowed directory
function validatePathWithinBase(basePath: string, userPath: string): string {
  const resolvedPath = resolve(basePath, userPath);
  const normalizedBase = normalize(basePath);
  if (!resolvedPath.startsWith(normalizedBase)) {
    throw new BadRequestException('Invalid file path — path traversal detected');
  }
  return resolvedPath;
}
```

### Request Body Size Limits

| Endpoint Type | Max Body Size | Implementation |
|---------------|--------------|----------------|
| Standard API (JSON) | 1 MB | `app.use(json({ limit: '1mb' }))` |
| File upload metadata | 1 MB | Same as standard |
| File upload (direct) | 50 MB | Presigned S3 URL (never through API body) |
| Bulk operation payload | 5 MB | Custom middleware on bulk routes |
| Webhook inbound | 256 KB | Custom middleware on webhook routes |

```typescript
// main.ts — global limits
app.use(json({ limit: '1mb' }));
app.use(urlencoded({ limit: '1mb', extended: true }));

// Per-route override for bulk endpoints
@Controller('domains/:domainId/recipients')
export class RecipientsController {
  @Post('bulk')
  @UseInterceptors(
    new PayloadSizeLimitInterceptor(5 * 1024 * 1024), // 5MB for bulk
  )
  bulkCreate(@Body() dto: BulkCreateRecipientsDto) { /* ... */ }
}
```

---

## CORS & CSP Configuration

### CORS Decision Matrix

| Environment | Allowed Origins | Credentials | Preflight Cache |
|-------------|----------------|-------------|-----------------|
| Development | `http://localhost:3000` | Yes | 1 hour |
| Staging | `https://staging.example.com` | Yes | 12 hours |
| Production | `https://app.example.com`, `https://admin.example.com` | Yes | 24 hours |
| API-only (external consumers) | `*` (public endpoints only) | No | 1 hour |

**Rules:**
- Production CORS origin is ALWAYS an explicit allowlist from environment variable.
- NEVER use `origin: '*'` with `credentials: true` (browsers block this).
- API keys are header-based, not cookie-based, so public API endpoints can use `*`.

### NestJS CORS Configuration

```typescript
// main.ts
app.enableCors({
  origin: (origin, callback) => {
    const allowedOrigins = process.env.ALLOWED_ORIGINS?.split(',') ?? [];

    // Allow requests with no origin (server-to-server, mobile, Postman)
    if (!origin) return callback(null, true);

    if (allowedOrigins.includes(origin)) {
      return callback(null, true);
    }

    callback(new ForbiddenException(`CORS: origin ${origin} not allowed`));
  },
  credentials: true,
  methods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: [
    'Content-Type',
    'Authorization',
    'x-workspace-id',
    'x-domain-id',
    'x-request-id',
  ],
  exposedHeaders: [
    'X-Request-Id',
    'X-RateLimit-Limit',
    'X-RateLimit-Remaining',
    'X-RateLimit-Reset',
    'Retry-After',
  ],
  maxAge: 86400, // 24 hours — reduces preflight requests
});
```

### CSP Directive Reference (For This Stack)

| Directive | Value | Reason |
|-----------|-------|--------|
| `default-src` | `'self'` | Baseline: only allow same-origin resources |
| `script-src` | `'self'` (+ nonce for inline if needed) | Block inline scripts. Use CSP nonces for Next.js inline scripts. |
| `style-src` | `'self' 'unsafe-inline'` | Tailwind CSS injects inline styles. Required until Tailwind supports extraction. |
| `img-src` | `'self' data: https:` | Profile photos (data URIs), CDN images (HTTPS) |
| `connect-src` | `'self' https://api.example.com` | API calls, SSE connections |
| `font-src` | `'self'` | Self-hosted fonts only |
| `object-src` | `'none'` | Block Flash, Java applets — no use case |
| `frame-src` | `'none'` (or specific embed origins) | Block iframes unless embedding specific providers |
| `frame-ancestors` | `'none'` | Prevent clickjacking — no one can iframe your app |
| `base-uri` | `'self'` | Prevent `<base>` tag injection |
| `form-action` | `'self'` | Prevent form submission to external URLs |
| `upgrade-insecure-requests` | (present) | Auto-upgrade HTTP to HTTPS |
| `report-uri` | `/csp-report` | Collect CSP violations for monitoring |

### Helmet.js Configuration (NestJS API)

```typescript
import helmet from 'helmet';

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", 'data:', 'https:'],
      connectSrc: ["'self'"],
      fontSrc: ["'self'"],
      objectSrc: ["'none'"],
      frameSrc: ["'none'"],
      frameAncestors: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
      upgradeInsecureRequests: [],
      reportUri: '/csp-report',
    },
    reportOnly: false, // Set to true during gradual rollout
  },
  crossOriginEmbedderPolicy: true,
  crossOriginOpenerPolicy: { policy: 'same-origin' },
  crossOriginResourcePolicy: { policy: 'same-origin' },
  referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
  hsts: { maxAge: 31536000, includeSubDomains: true, preload: true },
  noSniff: true,
  xssFilter: true,
  frameguard: { action: 'deny' },
}));
```

### CSP Report-Only Mode (Gradual Rollout)

Use report-only mode to catch violations before enforcing.

```typescript
// Phase 1: Report-only (2 weeks) — collect violations without blocking
contentSecurityPolicy: {
  directives: { /* ... */ },
  reportOnly: true,
}

// CSP violation report endpoint
@Controller('csp-report')
export class CspReportController {
  @Post()
  @SkipThrottle() // CSP reports should not be rate limited
  handleReport(@Body() report: CspViolationReport): void {
    this.logger.warn({
      event: 'csp_violation',
      directive: report['csp-report']?.['violated-directive'],
      blockedUri: report['csp-report']?.['blocked-uri'],
      documentUri: report['csp-report']?.['document-uri'],
    });
  }
}

// Phase 2: Enforce — after zero violations for 1 week
contentSecurityPolicy: {
  directives: { /* ... */ },
  reportOnly: false,
}
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
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: https:",
      "connect-src 'self' https://api.example.com",
      "font-src 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "upgrade-insecure-requests",
    ].join('; '),
  },
];

export default {
  async headers() {
    return [{ source: '/(.*)', headers: securityHeaders }];
  },
};
```

### Cookie Security Attributes

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `Secure` | `true` | Only sent over HTTPS |
| `HttpOnly` | `true` | Not accessible via JavaScript (XSS immune) |
| `SameSite` | `Strict` | Not sent on cross-origin requests (CSRF immune) |
| `Domain` | Omit (default to exact host) | Cookies not shared with subdomains unless explicit |
| `Path` | `/` for access token, `/auth/refresh` for refresh token | Refresh token only sent to refresh endpoint |
| `Max-Age` | 900 (access), 604800 (refresh) | Matches JWT expiry |

```typescript
// Cookie configuration
res.cookie('access_token', accessToken, {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'strict',
  maxAge: 15 * 60 * 1000,  // 15 minutes
  path: '/',
});

res.cookie('refresh_token', refreshToken, {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'strict',
  maxAge: 7 * 24 * 60 * 60 * 1000,  // 7 days
  path: '/auth/refresh',  // ONLY sent to refresh endpoint
});
```

---

## File Upload Security

### File Type Validation (Magic Bytes)

Never trust file extensions or `Content-Type` headers. Validate file content.

| File Type | Extension | Magic Bytes (Hex) | Allowed Max Size |
|-----------|-----------|-------------------|-----------------|
| CSV | `.csv` | None (text file — validate structure) | 50 MB |
| XLSX | `.xlsx` | `50 4B 03 04` (ZIP signature) | 25 MB |
| PNG | `.png` | `89 50 4E 47 0D 0A 1A 0A` | 10 MB |
| JPEG | `.jpg` | `FF D8 FF` | 10 MB |
| PDF | `.pdf` | `25 50 44 46` | 25 MB |

```typescript
import { fileTypeFromBuffer } from 'file-type';

@Injectable()
export class FileValidationService {
  private readonly ALLOWED_TYPES: Record<string, { mimes: string[]; maxSize: number }> = {
    csv: { mimes: ['text/csv', 'text/plain'], maxSize: 50 * 1024 * 1024 },
    xlsx: {
      mimes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
      maxSize: 25 * 1024 * 1024,
    },
    png: { mimes: ['image/png'], maxSize: 10 * 1024 * 1024 },
    jpeg: { mimes: ['image/jpeg'], maxSize: 10 * 1024 * 1024 },
    pdf: { mimes: ['application/pdf'], maxSize: 25 * 1024 * 1024 },
  };

  async validate(buffer: Buffer, declaredFilename: string): Promise<FileValidationResult> {
    // 1. Check file size before processing
    const maxAllowedSize = 50 * 1024 * 1024; // 50MB absolute max
    if (buffer.length > maxAllowedSize) {
      throw new PayloadTooLargeException('File exceeds maximum allowed size');
    }

    // 2. Detect actual file type via magic bytes
    const detected = await fileTypeFromBuffer(buffer);

    // 3. For CSV, magic byte detection won't work — validate structure
    const ext = declaredFilename.split('.').pop()?.toLowerCase();
    if (ext === 'csv' && !detected) {
      this.validateCsvStructure(buffer);
      return { type: 'csv', mime: 'text/csv', size: buffer.length };
    }

    if (!detected) {
      throw new BadRequestException('Unable to determine file type');
    }

    // 4. Verify detected type is in allowlist
    const allowedEntry = Object.entries(this.ALLOWED_TYPES).find(
      ([, config]) => config.mimes.includes(detected.mime),
    );
    if (!allowedEntry) {
      throw new BadRequestException(
        `File type ${detected.mime} is not allowed. Accepted: CSV, XLSX, PNG, JPEG, PDF`,
      );
    }

    // 5. Verify file size against type-specific limit
    const [typeName, config] = allowedEntry;
    if (buffer.length > config.maxSize) {
      throw new PayloadTooLargeException(
        `${typeName.toUpperCase()} files must be under ${config.maxSize / 1024 / 1024}MB`,
      );
    }

    return { type: typeName, mime: detected.mime, size: buffer.length };
  }

  private validateCsvStructure(buffer: Buffer): void {
    const sample = buffer.subarray(0, 4096).toString('utf-8');
    // Check for binary content (null bytes indicate this is not a text file)
    if (sample.includes('\0')) {
      throw new BadRequestException('File appears to be binary, not a valid CSV');
    }
    // Verify at least one line with comma or tab delimiters
    const lines = sample.split('\n');
    if (lines.length < 1 || (!lines[0].includes(',') && !lines[0].includes('\t'))) {
      throw new BadRequestException('File does not appear to be a valid CSV');
    }
  }
}
```

### Content Scanning (ClamAV)

```typescript
import NodeClam from 'clamscan';

@Injectable()
export class AntivirusService {
  private clam: NodeClam;

  async onModuleInit(): Promise<void> {
    this.clam = await new NodeClam().init({
      clamdscan: {
        host: process.env.CLAMAV_HOST ?? '127.0.0.1',
        port: parseInt(process.env.CLAMAV_PORT ?? '3310'),
        timeout: 30000,
      },
    });
  }

  async scan(buffer: Buffer): Promise<ScanResult> {
    const { isInfected, viruses } = await this.clam.scanBuffer(buffer);
    if (isInfected) {
      this.logger.error({
        event: 'malware_detected',
        viruses,
      });
      throw new BadRequestException('File failed security scan — upload rejected');
    }
    return { clean: true };
  }
}
```

### Storage Isolation

```
Storage path pattern:
  uploads/{companyId}/{workspaceId}/{domainId}/{purpose}/{uuid}/{sanitized-filename}

Examples:
  uploads/comp-a/ws-a1/dom-a1a/imports/550e8400-.../recipients.csv
  uploads/comp-a/ws-a1/dom-a1a/avatars/550e8400-.../photo.png

NEVER store uploads:
  - In the public web root
  - Without tenant scope in the path
  - With the original filename as the sole identifier
  - In a flat directory (use UUID subdirectories)
```

### Filename Sanitization

```typescript
function sanitizeUploadFilename(rawFilename: string): string {
  let safe = basename(rawFilename);
  safe = safe.normalize('NFC');
  safe = safe.replace(/\.\./g, '');
  safe = safe.replace(/[/\\]/g, '');
  safe = safe.replace(/\0/g, '');
  safe = safe.replace(/[^a-zA-Z0-9.\-_]/g, '_');
  if (safe.length > 200) {
    const ext = safe.split('.').pop() ?? '';
    safe = safe.substring(0, 200 - ext.length - 1) + '.' + ext;
  }
  if (safe.startsWith('.')) safe = '_' + safe;
  if (!safe || safe === '.') safe = 'unnamed';
  return safe;
}
```

### Image Processing Security

```typescript
import sharp from 'sharp';

async function processImageSecurely(buffer: Buffer): Promise<Buffer> {
  return sharp(buffer)
    .rotate()            // Apply EXIF orientation, then strip EXIF
    .withMetadata({})    // Strip ALL metadata (EXIF, GPS, camera info)
    .png()               // Re-encode to PNG (prevents polyglot attacks)
    .toBuffer();
}
```

Why re-encode? A file can be simultaneously valid as two formats (polyglot). Re-encoding strips any hidden payload.

### CSV Injection Prevention

Cells starting with `=`, `+`, `-`, `@` can trigger formula execution in Excel/Google Sheets.

```typescript
const CSV_INJECTION_PREFIXES = ['=', '+', '-', '@', '\t', '\r', '\n'];

function sanitizeCsvCellValue(value: string): string {
  if (typeof value !== 'string') return String(value);
  if (CSV_INJECTION_PREFIXES.some(prefix => value.startsWith(prefix))) {
    return "'" + value; // Prefix with single quote — renders as text in Excel
  }
  return value;
}

// Apply to every cell during import
function sanitizeCsvRow(row: Record<string, string>): Record<string, string> {
  const sanitized: Record<string, string> = {};
  for (const [key, value] of Object.entries(row)) {
    sanitized[sanitizeCsvCellValue(key)] = sanitizeCsvCellValue(value);
  }
  return sanitized;
}

// Apply to every cell during export (defense in depth)
function sanitizeCsvForExport(rows: Record<string, unknown>[]): Record<string, string>[] {
  return rows.map(row => {
    const sanitized: Record<string, string> = {};
    for (const [key, value] of Object.entries(row)) {
      sanitized[key] = sanitizeCsvCellValue(String(value ?? ''));
    }
    return sanitized;
  });
}
```

### Zip Bomb Detection (XLSX Files)

```typescript
const MAX_COMPRESSION_RATIO = 100; // 100:1 ratio is suspicious
const MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024; // 100MB

async function detectZipBomb(buffer: Buffer): Promise<void> {
  const compressedSize = buffer.length;

  // Use streaming decompression to check size without full extraction
  const zip = new AdmZip(buffer);
  let totalDecompressedSize = 0;

  for (const entry of zip.getEntries()) {
    totalDecompressedSize += entry.header.size;

    if (totalDecompressedSize > MAX_DECOMPRESSED_SIZE) {
      throw new BadRequestException(
        'File decompresses to an excessive size — possible zip bomb detected',
      );
    }
  }

  const ratio = totalDecompressedSize / compressedSize;
  if (ratio > MAX_COMPRESSION_RATIO) {
    throw new BadRequestException(
      `Suspicious compression ratio (${ratio.toFixed(0)}:1) — possible zip bomb`,
    );
  }
}
```

### Temporary File Cleanup

```typescript
// Cron job: purge orphaned uploads older than 24 hours
@Cron('0 */6 * * *') // Every 6 hours
async cleanupOrphanedUploads(): Promise<void> {
  const cutoff = subHours(new Date(), 24);

  // Find uploads not linked to any completed import/entity
  const orphaned = await this.db.query.uploads.findMany({
    where: and(
      lt(uploads.createdAt, cutoff),
      isNull(uploads.linkedEntityId), // not attached to any record
      eq(uploads.status, 'pending'),
    ),
    limit: 500, // batch to avoid long-running query
  });

  for (const upload of orphaned) {
    await this.storageService.delete(upload.storagePath);
    await this.db.delete(uploads).where(eq(uploads.id, upload.id));
  }

  if (orphaned.length > 0) {
    this.logger.info({
      event: 'orphaned_uploads_cleaned',
      count: orphaned.length,
    });
  }
}
```

---

## Webhook Security

### Outbound Webhook Signing (HMAC-SHA256)

Every outbound webhook delivery is signed with a per-tenant secret.

```typescript
import { createHmac, timingSafeEqual } from 'crypto';

@Injectable()
export class WebhookSigningService {
  // Generate signature for outbound webhook delivery
  sign(payload: string, secret: string, timestamp: number): string {
    // Include timestamp in signature to prevent replay
    const signedContent = `${timestamp}.${payload}`;
    return createHmac('sha256', secret)
      .update(signedContent)
      .digest('hex');
  }

  // Build headers for outbound delivery
  buildHeaders(payload: string, secret: string): Record<string, string> {
    const timestamp = Math.floor(Date.now() / 1000);
    const signature = this.sign(payload, secret, timestamp);

    return {
      'Content-Type': 'application/json',
      'X-Webhook-Signature': `v1=${signature}`,
      'X-Webhook-Timestamp': timestamp.toString(),
      'X-Webhook-Id': randomUUID(),
    };
  }

  // Verify inbound webhook from customer (if they mirror our signing)
  verify(payload: string, signature: string, secret: string, timestamp: number): boolean {
    // Check timestamp freshness (reject if >5 minutes old)
    const age = Math.floor(Date.now() / 1000) - timestamp;
    if (age > 300) return false;

    const expected = this.sign(payload, secret, timestamp);
    const sigValue = signature.replace('v1=', '');

    return timingSafeEqual(
      Buffer.from(sigValue, 'hex'),
      Buffer.from(expected, 'hex'),
    );
  }
}
```

### Outbound SSRF Prevention

User-provided webhook URLs must be validated to prevent SSRF.

```typescript
import { URL } from 'url';
import { lookup } from 'dns/promises';

const PRIVATE_IP_RANGES = [
  /^127\./,
  /^10\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^192\.168\./,
  /^169\.254\./,
  /^0\./,
  /^::1$/,
  /^fc00:/,
  /^fe80:/,
];

const BLOCKED_HOSTNAMES = [
  'localhost',
  'metadata.google.internal',
  'metadata.internal',
];

@Injectable()
export class WebhookUrlValidator {
  // Validate on registration AND on each delivery (DNS can change)
  async validate(url: string): Promise<void> {
    // 1. Parse URL
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      throw new BadRequestException('Invalid webhook URL');
    }

    // 2. HTTPS only
    if (parsed.protocol !== 'https:') {
      throw new BadRequestException('Webhook URL must use HTTPS');
    }

    // 3. No blocked hostnames
    if (BLOCKED_HOSTNAMES.includes(parsed.hostname)) {
      throw new BadRequestException('Webhook URL hostname is not allowed');
    }

    // 4. No IP addresses in URL (require domain names)
    if (/^\d{1,3}(\.\d{1,3}){3}$/.test(parsed.hostname)) {
      throw new BadRequestException('Webhook URL must use a domain name, not an IP address');
    }

    // 5. DNS resolution check — reject private IPs
    try {
      const { address } = await lookup(parsed.hostname);
      if (PRIVATE_IP_RANGES.some(range => range.test(address))) {
        throw new BadRequestException('Webhook URL resolves to a private IP address');
      }
    } catch (err) {
      if (err instanceof BadRequestException) throw err;
      throw new BadRequestException('Webhook URL DNS resolution failed');
    }

    // 6. No non-standard ports that might hit internal services
    if (parsed.port && !['443', '8443'].includes(parsed.port)) {
      throw new BadRequestException('Webhook URL must use port 443 or 8443');
    }
  }
}
```

### Outbound Retry Strategy

| Attempt | Delay | Total Elapsed |
|---------|-------|---------------|
| 1 (initial) | 0 | 0 |
| 2 | 30 seconds | 30s |
| 3 | 2 minutes | 2m 30s |
| 4 | 15 minutes | 17m 30s |
| 5 | 1 hour | 1h 17m 30s |
| Dead letter | N/A | Webhook disabled after 5 consecutive failures |

```typescript
@Processor('webhook-delivery')
export class WebhookDeliveryProcessor extends BaseProcessor {
  async process(job: Job<WebhookDeliveryPayload>): Promise<WebhookDeliveryResult> {
    const { url, payload, secret, tenantContext } = job.data;

    // Re-validate URL before each delivery (DNS rebinding protection)
    await this.urlValidator.validate(url);

    const body = JSON.stringify(payload);
    const headers = this.signingService.buildHeaders(body, secret);
    const startTime = Date.now();

    try {
      const response = await this.httpService.axiosRef.post(url, body, {
        headers,
        timeout: 5000,          // 5-second timeout per attempt
        maxRedirects: 0,        // No redirects (prevent SSRF via redirect)
        validateStatus: () => true, // Don't throw on non-2xx
      });

      const result: WebhookDeliveryResult = {
        statusCode: response.status,
        latencyMs: Date.now() - startTime,
        success: response.status >= 200 && response.status < 300,
      };

      // Log delivery attempt
      await this.logDelivery(tenantContext, job.data.webhookId, result, job.attemptsMade);

      if (!result.success && response.status >= 500) {
        throw new Error(`Webhook delivery failed with status ${response.status}`);
      }

      return result;
    } catch (err) {
      await this.logDelivery(tenantContext, job.data.webhookId, {
        statusCode: 0,
        latencyMs: Date.now() - startTime,
        success: false,
        error: err.message,
      }, job.attemptsMade);

      throw err; // BullMQ handles retry with backoff
    }
  }

  private async logDelivery(
    ctx: DomainContext,
    webhookId: string,
    result: WebhookDeliveryResult,
    attempt: number,
  ): Promise<void> {
    await this.db.insert(webhookDeliveryLogs).values({
      webhookId,
      companyId: ctx.companyId,
      workspaceId: ctx.workspaceId,
      statusCode: result.statusCode,
      latencyMs: result.latencyMs,
      success: result.success,
      error: result.error ?? null,
      attempt,
    });
  }
}

// Queue configuration
const webhookQueue = new Queue('webhook-delivery', {
  defaultJobOptions: {
    attempts: 5,
    backoff: {
      type: 'custom',
      // Custom strategy: 30s, 2m, 15m, 1h
    },
    removeOnComplete: { age: 86400, count: 1000 },
    removeOnFail: { age: 604800 }, // Keep failed for 7 days
  },
});
```

### Inbound Webhook Verification

```typescript
// Provider-specific verification strategies
interface WebhookVerifier {
  verify(req: Request): Promise<boolean>;
}

@Injectable()
export class StripeWebhookVerifier implements WebhookVerifier {
  async verify(req: Request): Promise<boolean> {
    const sig = req.headers['stripe-signature'];
    const rawBody = req['rawBody']; // Requires raw body middleware
    try {
      stripe.webhooks.constructEvent(rawBody, sig, process.env.STRIPE_WEBHOOK_SECRET);
      return true;
    } catch {
      return false;
    }
  }
}

@Injectable()
export class GenericHmacVerifier implements WebhookVerifier {
  async verify(req: Request): Promise<boolean> {
    const signature = req.headers['x-webhook-signature'] as string;
    const timestamp = parseInt(req.headers['x-webhook-timestamp'] as string, 10);
    const rawBody = req['rawBody'];

    if (!signature || !timestamp || !rawBody) return false;

    // Check timestamp freshness (reject >5 min old)
    const age = Math.floor(Date.now() / 1000) - timestamp;
    if (age > 300 || age < -60) return false;

    // Verify signature
    const secret = await this.getSecretForSource(req);
    const expected = createHmac('sha256', secret)
      .update(`${timestamp}.${rawBody}`)
      .digest('hex');

    return timingSafeEqual(
      Buffer.from(signature.replace('v1=', ''), 'hex'),
      Buffer.from(expected, 'hex'),
    );
  }
}

// Inbound webhook verification middleware
@Injectable()
export class WebhookVerificationGuard implements CanActivate {
  constructor(private readonly verifierFactory: WebhookVerifierFactory) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const provider = req.params.provider;

    const verifier = this.verifierFactory.getVerifier(provider);
    if (!verifier) {
      throw new BadRequestException(`Unknown webhook provider: ${provider}`);
    }

    const valid = await verifier.verify(req);
    if (!valid) {
      this.logger.warn({
        event: 'webhook_verification_failed',
        provider,
        ip: req.ip,
      });
      throw new UnauthorizedException('Webhook signature verification failed');
    }

    return true;
  }
}
```

### Inbound Replay Prevention

```typescript
@Injectable()
export class WebhookReplayGuard {
  constructor(@Inject('REDIS') private readonly redis: Redis) {}

  async checkAndMark(webhookId: string, provider: string): Promise<void> {
    const key = `webhook-seen:${provider}:${webhookId}`;

    // NX = only set if not exists, EX = expire after 24 hours
    const isNew = await this.redis.set(key, '1', 'EX', 86400, 'NX');
    if (!isNew) {
      throw new ConflictException('Webhook already processed (duplicate delivery)');
    }
  }
}
```

### Webhook Event Payload Structure (Standardized Envelope)

```typescript
interface WebhookPayload<T = Record<string, unknown>> {
  id: string;               // Unique delivery ID (UUID)
  type: string;             // Event type (e.g., "recipient.created")
  apiVersion: string;       // API version (e.g., "2025-01-01")
  createdAt: string;        // ISO 8601 timestamp
  workspaceId: string;      // Which workspace generated this event
  data: T;                  // Event-specific payload (IDs, not full objects)
}

// Event type catalog
type WebhookEventType =
  | 'recipient.created'
  | 'recipient.updated'
  | 'recipient.deleted'
  | 'campaign.sent'
  | 'campaign.completed'
  | 'import.completed'
  | 'import.failed'
  | 'training.completed'
  | 'domain.created'
  | 'domain.deleted';
```

---

## API Abuse Prevention

### Enumeration Attack Prevention

User existence, email discovery, and resource enumeration attacks rely on differences in response time or content.

| Scenario | Insecure Response | Secure Response |
|----------|-------------------|-----------------|
| Login: invalid email | 400 "User not found" (fast) | 401 "Invalid credentials" (constant time) |
| Login: wrong password | 401 "Wrong password" (slow — bcrypt) | 401 "Invalid credentials" (constant time) |
| Forgot password: unknown email | 404 "Email not found" | 200 "If that email exists, a reset link was sent" |
| Registration: existing email | 409 "Email already taken" | 200 "Check your email" (send different emails for new vs existing) |
| GET resource: no access | 403 "Forbidden" | 403 "Forbidden" (not 404 — see note below) |

**Constant-time login implementation:**

```typescript
async login(email: string, password: string): Promise<TokenPair> {
  const user = await this.userRepo.findByEmail(email);

  // ALWAYS hash — even if user doesn't exist
  // This prevents timing attacks that distinguish "user exists" from "user doesn't exist"
  const dummyHash = '$2b$12$dummyhashfortimingequalityxxxxxxxxxxxxxxxxxxxxxxxxxx';
  const hashToCompare = user?.passwordHash ?? dummyHash;
  const valid = await bcrypt.compare(password, hashToCompare);

  if (!user || !valid) {
    // Same error message regardless of which check failed
    throw new UnauthorizedException('Invalid credentials');
  }

  return this.tokenService.generateTokenPair(user, user.defaultWorkspaceId);
}
```

### Scraping Prevention

| Control | Implementation | Purpose |
|---------|---------------|---------|
| Max page size | `@Max(100)` on `limit` parameter | Prevent bulk data extraction |
| Pagination depth limit | `offset` max 10,000 (use cursor after that) | Prevent deep enumeration |
| Cursor expiry | HMAC-signed cursors with embedded timestamp (1 hour max) | Prevent long-running scrapers |
| No total count on large tables | Omit `totalCount` for tables >100K rows (or use estimate) | Prevent size discovery |
| Consistent response shapes | Always return same fields, even if empty | Prevent inference from response structure |

### Resource Exhaustion Protection

```typescript
// Query complexity guard — prevents expensive queries
@Injectable()
export class QueryComplexityGuard implements CanActivate {
  private readonly MAX_FILTER_DEPTH = 3;     // No more than 3 nested AND/OR
  private readonly MAX_FILTER_CONDITIONS = 10; // Max 10 conditions per query
  private readonly MAX_IN_VALUES = 100;       // Max 100 values in IN clause
  private readonly QUERY_TIMEOUT_MS = 30000;  // 30-second timeout

  canActivate(context: ExecutionContext): boolean {
    const req = context.switchToHttp().getRequest();
    const filter = req.query.filter || req.body?.filter;

    if (!filter) return true;

    let parsed: Record<string, unknown>;
    try {
      parsed = typeof filter === 'string' ? JSON.parse(filter) : filter;
    } catch {
      throw new BadRequestException('Invalid filter syntax');
    }

    // Check nesting depth
    const depth = this.measureDepth(parsed);
    if (depth > this.MAX_FILTER_DEPTH) {
      throw new BadRequestException(
        `Filter nesting too deep (${depth}). Maximum: ${this.MAX_FILTER_DEPTH}`,
      );
    }

    // Check condition count
    const conditions = this.countConditions(parsed);
    if (conditions > this.MAX_FILTER_CONDITIONS) {
      throw new BadRequestException(
        `Too many filter conditions (${conditions}). Maximum: ${this.MAX_FILTER_CONDITIONS}`,
      );
    }

    // Check IN clause size
    this.validateInClauseSizes(parsed);

    return true;
  }

  private measureDepth(obj: unknown, current = 0): number {
    if (!obj || typeof obj !== 'object') return current;
    return Math.max(
      ...Object.values(obj).map(v => this.measureDepth(v, current + 1)),
      current,
    );
  }

  private countConditions(obj: unknown): number {
    if (!obj || typeof obj !== 'object') return 0;
    let count = 0;
    for (const value of Object.values(obj)) {
      if (typeof value === 'object' && value !== null) {
        count += this.countConditions(value);
      } else {
        count += 1;
      }
    }
    return count;
  }

  private validateInClauseSizes(obj: unknown): void {
    if (!obj || typeof obj !== 'object') return;
    for (const [key, value] of Object.entries(obj)) {
      if (key === '$in' && Array.isArray(value) && value.length > this.MAX_IN_VALUES) {
        throw new BadRequestException(
          `IN clause too large (${value.length}). Maximum: ${this.MAX_IN_VALUES}`,
        );
      }
      if (typeof value === 'object') {
        this.validateInClauseSizes(value);
      }
    }
  }
}
```

### Batch Endpoint Abuse Prevention

```typescript
export class BulkOperationDto {
  @IsArray()
  @ArrayMinSize(1)
  @ArrayMaxSize(1000) // Hard cap — no exceptions
  @ValidateNested({ each: true })
  @Type(() => RecipientDto)
  items: RecipientDto[];
}

// For larger batches (>1000), require BullMQ job
@Controller('domains/:domainId/recipients')
export class RecipientsController {
  @Post('bulk')
  @CheckAbility({ action: 'create', subject: 'Recipient' })
  async bulkCreate(
    @Body() dto: BulkOperationDto,
    @TenantCtx() ctx: DomainContext,
  ): Promise<BulkResult> {
    // Inline processing for <=1000 items
    return this.recipientService.bulkCreate(dto.items, ctx);
  }

  @Post('bulk-async')
  @CheckAbility({ action: 'create', subject: 'Recipient' })
  async bulkCreateAsync(
    @Body() dto: AsyncBulkOperationDto, // allows >1000 via file reference
    @TenantCtx() ctx: DomainContext,
  ): Promise<{ jobId: string }> {
    // Queue for background processing
    return this.recipientService.queueBulkCreate(dto, ctx);
  }
}
```

### SSE Stream Abuse Prevention

```typescript
@Injectable()
export class SseConnectionManager {
  private readonly MAX_STREAMS_PER_USER = 5;
  private readonly HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds
  private readonly MAX_STREAM_DURATION_MS = 3600000; // 1 hour
  private readonly connections = new Map<string, Set<string>>();

  async registerStream(userId: string, streamId: string): Promise<void> {
    const userKey = `sse-streams:${userId}`;
    const count = await this.redis.scard(userKey);

    if (count >= this.MAX_STREAMS_PER_USER) {
      throw new TooManyRequestsException(
        `Maximum ${this.MAX_STREAMS_PER_USER} concurrent SSE connections per user`,
      );
    }

    await this.redis.sadd(userKey, streamId);
    await this.redis.expire(userKey, Math.ceil(this.MAX_STREAM_DURATION_MS / 1000));
  }

  async unregisterStream(userId: string, streamId: string): Promise<void> {
    await this.redis.srem(`sse-streams:${userId}`, streamId);
  }

  // SSE endpoint with connection management
  @Sse('domains/:domainId/jobs/:jobId/progress')
  @UseGuards(JwtAuthGuard, DomainContextGuard)
  async streamProgress(
    @Param('jobId') jobId: string,
    @CurrentUser() user: AccessTokenPayload,
    @TenantCtx() ctx: DomainContext,
  ): Promise<Observable<MessageEvent>> {
    // Validate job belongs to this tenant
    const job = await this.jobService.findById(jobId, ctx.domainId);
    if (!job) throw new NotFoundException('Job not found');

    const streamId = randomUUID();
    await this.connectionManager.registerStream(user.sub, streamId);

    const startTime = Date.now();

    return new Observable<MessageEvent>(subscriber => {
      // Heartbeat to detect dead connections
      const heartbeat = setInterval(() => {
        if (Date.now() - startTime > this.MAX_STREAM_DURATION_MS) {
          subscriber.complete();
          return;
        }
        subscriber.next({ data: JSON.stringify({ type: 'heartbeat' }) } as MessageEvent);
      }, this.HEARTBEAT_INTERVAL_MS);

      // Progress events from Redis pub/sub
      const channel = `job-progress:${ctx.domainId}:${jobId}`;
      this.redis.subscribe(channel, (message) => {
        subscriber.next({ data: message } as MessageEvent);
      });

      // Cleanup on disconnect
      return () => {
        clearInterval(heartbeat);
        this.redis.unsubscribe(channel);
        this.connectionManager.unregisterStream(user.sub, streamId);
      };
    });
  }
}
```

### Slowloris / Connection Exhaustion

Configure at the reverse proxy level (upstream from NestJS).

| Setting | Value | Purpose |
|---------|-------|---------|
| `client_header_timeout` | 10s | Drop slow header senders |
| `client_body_timeout` | 30s | Drop slow body senders |
| `keepalive_timeout` | 65s | Close idle connections |
| `send_timeout` | 30s | Drop slow readers |
| `limit_conn_per_ip` | 50 | Max connections per IP |
| `worker_connections` | 1024 | Max total connections per worker |

---

## Error Handling Security

### Error Response Structure

Every error response uses the same shape. No internal details leak.

```typescript
interface ErrorResponse {
  statusCode: number;       // HTTP status code
  error: string;            // HTTP status text (e.g., "Bad Request")
  message: string;          // User-safe message
  requestId: string;        // Correlation ID (X-Request-Id)
  timestamp: string;        // ISO 8601
}
```

### Global Exception Filter

```typescript
@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger('ExceptionFilter');

  catch(exception: unknown, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const res = ctx.getResponse<Response>();
    const req = ctx.getRequest<Request>();
    const requestId = req.headers['x-request-id'] ?? randomUUID();

    const { status, message, internalMessage } = this.resolveException(exception);

    // Log full details server-side (with correlation ID)
    this.logger.error({
      requestId,
      statusCode: status,
      path: req.url,
      method: req.method,
      message: internalMessage,
      stack: exception instanceof Error ? exception.stack : undefined,
      userId: req['user']?.sub,
      tenantId: req['user']?.companyId,
    });

    // Return safe response to client (no stack traces, no SQL, no internal paths)
    res.status(status).json({
      statusCode: status,
      error: HttpStatus[status] ?? 'Internal Server Error',
      message,
      requestId,
      timestamp: new Date().toISOString(),
    });
  }

  private resolveException(exception: unknown): {
    status: number;
    message: string;
    internalMessage: string;
  } {
    // NestJS HTTP exceptions — use their message directly (developer-controlled)
    if (exception instanceof HttpException) {
      const response = exception.getResponse();
      const message = typeof response === 'string'
        ? response
        : (response as any).message ?? exception.message;
      return {
        status: exception.getStatus(),
        message: Array.isArray(message) ? message.join(', ') : message,
        internalMessage: exception.message,
      };
    }

    // Database errors — mask internal details
    if (this.isDatabaseError(exception)) {
      return this.maskDatabaseError(exception);
    }

    // All other errors — generic 500
    return {
      status: 500,
      message: 'An unexpected error occurred. Please try again or contact support.',
      internalMessage: exception instanceof Error ? exception.message : String(exception),
    };
  }

  private isDatabaseError(err: unknown): boolean {
    return err instanceof Error && 'code' in err && typeof (err as any).code === 'string';
  }

  private maskDatabaseError(err: unknown): { status: number; message: string; internalMessage: string } {
    const dbErr = err as { code: string; detail?: string; message: string };

    const DB_ERROR_MAP: Record<string, { status: number; message: string }> = {
      '23505': { status: 409, message: 'A record with this value already exists' },
      '23503': { status: 400, message: 'Referenced record does not exist' },
      '23502': { status: 400, message: 'A required field is missing' },
      '23514': { status: 400, message: 'Value does not meet requirements' },
      '42P01': { status: 500, message: 'An unexpected error occurred' }, // undefined table — server bug
      '57014': { status: 504, message: 'Request timed out. Please try a smaller operation.' }, // query timeout
    };

    const mapped = DB_ERROR_MAP[dbErr.code];
    if (mapped) {
      return { ...mapped, internalMessage: `DB error ${dbErr.code}: ${dbErr.detail ?? dbErr.message}` };
    }

    return {
      status: 500,
      message: 'An unexpected error occurred',
      internalMessage: `Unmapped DB error ${dbErr.code}: ${dbErr.message}`,
    };
  }
}
```

### Safe vs Unsafe Error Messages

| Category | Unsafe (Never Return) | Safe (Return to Client) |
|----------|----------------------|------------------------|
| Database | `duplicate key value violates unique constraint "recipients_domain_id_email_unique"` | `A recipient with this email already exists` |
| Database | `insert or update on table "recipients" violates foreign key constraint "fk_domain"` | `Referenced record does not exist` |
| Database | `relation "recipients" does not exist` | `An unexpected error occurred` |
| Auth | `JWT signature verification failed: invalid RS256 key` | `Authentication failed` |
| Auth | `User john@company.com not found in database` | `Invalid credentials` |
| Validation | Stack trace from class-validator | `Validation failed: email must be a valid email address` |
| File | `/tmp/uploads/comp-abc/ws-123/file.csv: ENOENT` | `File not found or has expired` |
| Network | `ECONNREFUSED 10.0.1.5:5432` | `Service temporarily unavailable` |
| Memory | `JavaScript heap out of memory` | `Request too large. Please try a smaller operation.` |
| Permission | `CASL cannot('delete', 'Recipient') for user.role=user` | `You do not have permission to perform this action` |

### 404 vs 403 Decision

| Scenario | Return 404 | Return 403 | Rationale |
|----------|-----------|-----------|-----------|
| Resource does not exist at all | Yes | No | No information leak — resource genuinely doesn't exist |
| Resource exists in another tenant | No | Yes | Returning 404 is also acceptable here (see note) |
| Resource exists, user lacks permission | No | Yes | User knows it exists but cannot access it |
| Admin panel route for non-admin | No | Yes | Route existence is public knowledge |
| Webhook endpoint with wrong token | Yes | No | Don't confirm endpoint existence to scanners |

**Note on 403 vs 404 for cross-tenant:** The SKILL.md convention for this project is to return 403 for cross-tenant access (not 404). This is a conscious choice: the DomainContextGuard rejects before the repository query, so we cannot distinguish "doesn't exist" from "wrong tenant" without an extra query. Returning 403 is simpler and equally secure (the attacker learns the resource might exist somewhere, but not in which tenant).

### Correlation IDs (X-Request-Id)

Every request gets a unique correlation ID for tracing.

```typescript
@Injectable()
export class RequestIdMiddleware implements NestMiddleware {
  use(req: Request, _res: Response, next: NextFunction): void {
    // Use client-provided ID if present (for end-to-end tracing)
    // Otherwise generate one
    if (!req.headers['x-request-id']) {
      req.headers['x-request-id'] = randomUUID();
    }
    next();
  }
}

// Expose in response headers
@Injectable()
export class RequestIdInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const req = context.switchToHttp().getRequest();
    const res = context.switchToHttp().getResponse();
    res.setHeader('X-Request-Id', req.headers['x-request-id']);
    return next.handle();
  }
}
```

The request ID is:
- Attached to every log entry (via Pino context)
- Included in every error response
- Passed to BullMQ jobs as `correlationId`
- Returned to client in `X-Request-Id` header
- Used by support to locate logs without exposing internal details to the client
