# Patterns Reference — Design Patterns, Guards, Decorators, Processors

> Read this file when implementing cross-cutting concerns, external integrations,
> or job processing infrastructure.

---

## Table of Contents
1. [TenantContextGuard](#tenantcontextguard)
2. [Adapter Pattern (External Providers)](#adapter-pattern)
3. [Manager Pattern (Runtime Selection)](#manager-pattern)
4. [Strategy Pattern (Plan Limits)](#strategy-pattern)
5. [BaseProcessor (All Jobs)](#baseprocessor)
6. [@Audit Decorator + Interceptor](#audit-decorator)
7. [Repository Pattern with Drizzle](#repository-pattern)

---

## TenantContextGuard

Resolves the full company→workspace→domain hierarchy from Redis on every request.
Attaches to `request.tenantContext`. Checks subscription status.

```typescript
interface DomainContext {
  domainId: string;
  workspaceId: string;
  companyId: string;
  subscriptionTier: 'free' | 'pro' | 'business' | 'enterprise';
  subscriptionStatus: 'active' | 'past_due' | 'cancelled' | 'trialing';
  seatsLimit: number;
  recipientLimit: number;
}

@Injectable()
export class TenantContextGuard implements CanActivate {
  constructor(
    @Inject('REDIS') private readonly redis: Redis,
    private readonly domainRepo: DomainRepository,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const domainId = req.params.domainId || req.headers['x-domain-id'];
    if (!domainId) return true; // workspace-level or admin route

    const cacheKey = `domain:${domainId}:context`;
    let raw = await this.redis.get(cacheKey);

    if (!raw) {
      const ctx = await this.domainRepo.buildContext(domainId);
      if (!ctx) throw new NotFoundException('Domain not found');
      await this.redis.set(cacheKey, JSON.stringify(ctx), 'EX', 3600);
      raw = JSON.stringify(ctx);
    }

    const tenantContext: DomainContext = JSON.parse(raw);
    if (tenantContext.subscriptionStatus !== 'active' &&
        tenantContext.subscriptionStatus !== 'trialing') {
      throw new ForbiddenException('Subscription inactive');
    }

    req.tenantContext = tenantContext;
    return true;
  }
}

// DomainRepository.buildContext() — one-time DB query on cache miss:
async buildContext(domainId: string): Promise<DomainContext | null> {
  const result = await this.db.select({
    domainId: domains.id,
    workspaceId: workspaces.id,
    companyId: companies.id,
    subscriptionTier: companies.subscriptionTier,
    subscriptionStatus: companies.subscriptionStatus,
    seatsLimit: companies.seatsLimit,
    recipientLimit: companies.recipientLimit,
  })
    .from(domains)
    .innerJoin(workspaces, eq(domains.workspaceId, workspaces.id))
    .innerJoin(companies, eq(workspaces.companyId, companies.id))
    .where(eq(domains.id, domainId))
    .limit(1);
  return result[0] ?? null;
}
```

---

## Adapter Pattern

Use when multiple external providers implement the same logical contract.
Triggers: SSO providers, storage backends, email senders, payment gateways.

```typescript
// Interface — all adapters implement this
export interface IdentityAdapter {
  readonly provider: string;
  getAuthorizationUrl(config: SsoConnection, state: string): Promise<string>;
  exchangeCodeForTokens(config: SsoConnection, code: string): Promise<OAuthTokens>;
  getUserProfile(accessToken: string): Promise<ExternalUserProfile>;
  syncDirectory(config: SsoConnection, workspaceId: string): Promise<DirectorySyncResult>;
  validateWebhook?(payload: unknown, signature: string): boolean;
}

// Microsoft AD adapter — uses @azure/msal-node
@Injectable()
export class MicrosoftAdAdapter implements IdentityAdapter {
  readonly provider = 'microsoft_ad';

  async syncDirectory(config: SsoConnection, workspaceId: string): Promise<DirectorySyncResult> {
    const token = await this.getValidToken(config);
    let nextLink: string | undefined;
    let synced = 0;

    do {
      const url = nextLink ??
        'https://graph.microsoft.com/v1.0/users?$select=id,displayName,mail&$top=999';
      const res = await this.graphClient.get(url, token);
      await this.upsertUsers(workspaceId, res.value); // batch upsert
      synced += res.value.length;
      nextLink = res['@odata.nextLink'];
    } while (nextLink);

    return { provider: 'microsoft_ad', synced };
  }

  private async getValidToken(config: SsoConnection): Promise<string> {
    if (config.tokenExpiresAt && isAfter(config.tokenExpiresAt, addMinutes(new Date(), 5))) {
      return config.accessToken!;
    }
    const tokens = await this.msalClient.acquireTokenByRefreshToken({
      refreshToken: config.refreshToken!,
    });
    await this.ssoRepo.updateTokens(config.id, tokens);
    return tokens.accessToken;
  }
}

// Google Workspace adapter — uses googleapis
// Okta adapter — uses @okta/okta-sdk-nodejs
// SAML adapter — uses samlify
```

---

## Manager Pattern

One entry point routes to the correct adapter based on runtime context.

```typescript
@Injectable()
export class IdentityManager {
  private adapters: Map<string, IdentityAdapter>;

  constructor(
    msAd: MicrosoftAdAdapter,
    google: GoogleWorkspaceAdapter,
    okta: OktaAdapter,
    saml: SamlAdapter,
  ) {
    this.adapters = new Map([
      ['microsoft_ad', msAd],
      ['google', google],
      ['okta', okta],
      ['saml', saml],
    ]);
  }

  forProvider(provider: string): IdentityAdapter {
    const adapter = this.adapters.get(provider);
    if (!adapter) throw new BadRequestException(`Unknown SSO provider: ${provider}`);
    return adapter;
  }
}

// Service — thin orchestrator, delegates to adapters
@Injectable()
export class IdentityService {
  constructor(
    private readonly manager: IdentityManager,
    private readonly ssoRepo: SsoConnectionRepository,
    private readonly auditService: AuditService,
  ) {}

  async initiateLogin(workspaceId: string, state: string) {
    const conn = await this.ssoRepo.getActiveConnection(workspaceId);
    return this.manager.forProvider(conn.provider).getAuthorizationUrl(conn, state);
  }

  async syncDirectory(workspaceId: string, triggeredBy: string) {
    const conn = await this.ssoRepo.getActiveConnection(workspaceId);
    const result = await this.manager.forProvider(conn.provider)
      .syncDirectory(conn, workspaceId);
    this.auditService.log({
      workspaceId, actorId: triggeredBy,
      action: 'directory.synced',
      metadata: { provider: conn.provider, synced: result.synced },
    });
    return result;
  }
}
```

---

## Strategy Pattern

Same operation has different rules/limits based on subscription plan.

```typescript
export interface PlanStrategy {
  readonly plan: string;
  maxRecipientsPerImport(): number;
  maxCustomFields(): number;
  canUseSSO(): boolean;
  canUseApiKeys(): boolean;
  maxDomainsPerWorkspace(): number;
}

@Injectable()
export class FreePlanStrategy implements PlanStrategy {
  readonly plan = 'free';
  maxRecipientsPerImport() { return 1_000; }
  maxCustomFields() { return 5; }
  canUseSSO() { return false; }
  canUseApiKeys() { return false; }
  maxDomainsPerWorkspace() { return 1; }
}

@Injectable()
export class ProPlanStrategy implements PlanStrategy {
  readonly plan = 'pro';
  maxRecipientsPerImport() { return 50_000; }
  maxCustomFields() { return 50; }
  canUseSSO() { return false; }
  canUseApiKeys() { return true; }
  maxDomainsPerWorkspace() { return 10; }
}

@Injectable()
export class EnterprisePlanStrategy implements PlanStrategy {
  readonly plan = 'enterprise';
  maxRecipientsPerImport() { return 500_000; }
  maxCustomFields() { return 200; }
  canUseSSO() { return true; }
  canUseApiKeys() { return true; }
  maxDomainsPerWorkspace() { return -1; } // unlimited
}

// PlanManager resolves strategy from tenantContext
@Injectable()
export class PlanManager {
  private strategies: Map<string, PlanStrategy>;

  constructor(free: FreePlanStrategy, pro: ProPlanStrategy, ent: EnterprisePlanStrategy) {
    this.strategies = new Map([
      ['free', free], ['pro', pro], ['enterprise', ent],
    ]);
  }

  forTier(tier: string): PlanStrategy {
    return this.strategies.get(tier) ?? this.strategies.get('free')!;
  }
}
```

---

## BaseProcessor

ALL BullMQ job processors MUST extend this. It handles:
- Automatic job_logs write on success AND failure
- Dead letter queue on final attempt failure
- Duration tracking

```typescript
export abstract class BaseProcessor extends WorkerHost {
  abstract processJob(job: Job): Promise<unknown>;

  constructor(
    protected readonly jobLogRepo: JobLogRepository,
    protected readonly deadLetterQueue: Queue,
  ) { super(); }

  async process(job: Job): Promise<unknown> {
    const startedAt = new Date();
    let status = 'completed';
    let error: string | undefined;
    let stackTrace: string | undefined;

    try {
      return await this.processJob(job);
    } catch (err) {
      status = 'failed';
      error = err.message;
      stackTrace = err.stack;

      if (job.attemptsMade >= (job.opts.attempts ?? 3) - 1) {
        await this.deadLetterQueue.add('failed-job', {
          originalQueue: job.queueName,
          originalJobId: job.id,
          originalPayload: job.data,
          error: err.message,
          failedAt: new Date().toISOString(),
        });
      }
      throw err;
    } finally {
      await this.jobLogRepo.record({
        companyId: job.data.tenantContext?.companyId,
        workspaceId: job.data.tenantContext?.workspaceId,
        domainId: job.data.domainId,
        queueName: job.queueName,
        jobName: job.name,
        jobId: String(job.id),
        payload: job.data,
        status,
        attempts: job.attemptsMade + 1,
        maxAttempts: job.opts.attempts ?? 3,
        error,
        stackTrace,
        startedAt,
        completedAt: new Date(),
        durationMs: Date.now() - startedAt.getTime(),
      });
    }
  }
}

// Every processor implements ONE method:
@Processor('recipients')
export class BulkUpdateProcessor extends BaseProcessor {
  async processJob(job: Job<BulkUpdatePayload>) {
    const { domainId, filter, updates } = job.data;
    const batchSize = 500;
    let processed = 0;
    const total = await this.repo.countByFilter(domainId, filter);

    while (processed < total) {
      await this.repo.batchUpdate(domainId, filter, updates, batchSize, processed);
      processed = Math.min(processed + batchSize, total);
      await this.redis.set(`job:${job.id}:progress`, JSON.stringify({
        status: 'processing', processed, total,
        percentage: Math.round((processed / total) * 100),
      }), 'EX', 3600);
    }

    await this.redis.set(`job:${job.id}:progress`, JSON.stringify({
      status: 'completed', processed: total, total, percentage: 100,
    }), 'EX', 3600);
  }
}
```

---

## @Audit Decorator

Apply to any controller method. The interceptor auto-logs on success AND failure.

```typescript
// Decorator
export const Audit = (action: string) => SetMetadata('audit_action', action);

// Interceptor
@Injectable()
export class AuditLogInterceptor implements NestInterceptor {
  constructor(
    private readonly reflector: Reflector,
    private readonly auditService: AuditService,
  ) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const action = this.reflector.get<string>('audit_action', context.getHandler());
    if (!action) return next.handle();

    const req = context.switchToHttp().getRequest();
    const user = req.user;

    return next.handle().pipe(
      tap(() => {
        this.auditService.log({
          companyId: req.tenantContext?.companyId,
          workspaceId: req.tenantContext?.workspaceId ?? req.params.workspaceId,
          domainId: req.params.domainId,
          actorId: user?.id,
          actorEmail: user?.email,
          actorType: req.isImpersonating ? 'admin_impersonation' : 'user',
          action,
          status: 'success',
          ipAddress: req.ip,
          userAgent: req.headers['user-agent'],
        });
      }),
      catchError((err) => {
        this.auditService.log({
          companyId: req.tenantContext?.companyId,
          workspaceId: req.tenantContext?.workspaceId ?? req.params.workspaceId,
          domainId: req.params.domainId,
          actorId: user?.id,
          action,
          status: 'failure',
          errorMessage: err.message,
        });
        throw err;
      }),
    );
  }
}

// AuditService — fire-and-forget for normal ops, sync for admin
@Injectable()
export class AuditService {
  log(payload: AuditLogPayload): void {
    setImmediate(async () => {
      try { await this.repo.insert(payload); }
      catch (err) { console.error('[AuditService] Write failed', err); }
    });
  }

  async logSync(payload: AuditLogPayload): Promise<void> {
    await this.repo.insert(payload);
  }
}
```

---

## Repository Pattern

Every repository follows these rules:
1. `domain_id` is ALWAYS the first WHERE condition on hot-path queries
2. Use `and()` to compose filters
3. Paginate with limit/offset
4. Never loop queries — use JOIN or inArray

```typescript
@Injectable()
export class RecipientsRepository {
  constructor(@Inject(DB_TOKEN) private readonly db: DB) {}

  async findMany(domainId: string, filter: RecipientFilterDto) {
    const conditions = [eq(recipients.domainId, domainId)];

    if (filter.status) conditions.push(eq(recipients.status, filter.status));
    if (filter.search) conditions.push(ilike(recipients.email, `%${filter.search}%`));
    if (filter.customFields) {
      for (const [key, val] of Object.entries(filter.customFields)) {
        conditions.push(sql`${recipients.customFields}->>${key} = ${String(val)}`);
      }
    }

    const [rows, [{ total }]] = await Promise.all([
      this.db.select().from(recipients)
        .where(and(...conditions))
        .orderBy(desc(recipients.createdAt))
        .limit(filter.limit ?? 50)
        .offset(filter.offset ?? 0),
      this.db.select({ total: count() }).from(recipients)
        .where(and(...conditions)),
    ]);

    return { rows, total: Number(total) };
  }

  // JOIN pattern — recipient + email extension
  async findWithEmailData(domainId: string, recipientId: string) {
    return this.db.select({
      recipient: recipients,
      emailData: emailRecipients,
    })
      .from(recipients)
      .leftJoin(emailRecipients, eq(recipients.id, emailRecipients.recipientId))
      .where(and(
        eq(recipients.domainId, domainId),
        eq(recipients.id, recipientId),
      ));
  }

  // Batch IN pattern — avoid N+1
  async findExtensionsForMany(recipientIds: string[]) {
    const [email, sms, push] = await Promise.all([
      this.db.select().from(emailRecipients)
        .where(inArray(emailRecipients.recipientId, recipientIds)),
      this.db.select().from(smsRecipients)
        .where(inArray(smsRecipients.recipientId, recipientIds)),
      this.db.select().from(pushRecipients)
        .where(inArray(pushRecipients.recipientId, recipientIds)),
    ]);
    // Group by recipientId in memory
    return { email, sms, push };
  }
}
```
