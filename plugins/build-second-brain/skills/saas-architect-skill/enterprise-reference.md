# Enterprise Reference — Admin, Impersonation, SSO, Import Flow

> Read this file when implementing admin panels, SSO integrations,
> impersonation, or file import workflows.

---

## Table of Contents
1. [Admin Module](#admin-module)
2. [Impersonation Service](#impersonation-service)
3. [SSO Flow (End-to-End)](#sso-flow)
4. [File Import Flow](#file-import-flow)
5. [Domain Migration Handler](#domain-migration-handler)
6. [BullMQ Queue Configuration](#bullmq-queue-configuration)

---

## Admin Module

Completely separate from workspace API. Different guards, different JWT, MFA required.

```typescript
@Controller('admin')
@UseGuards(AdminJwtGuard, AdminMfaGuard)
export class AdminController {

  @Get('workspaces')
  listWorkspaces(@Query() filter: AdminWorkspaceFilterDto) {
    return this.adminService.listWorkspaces(filter);
  }

  @Patch('workspaces/:workspaceId')
  @RequireRole('super_admin')
  @Audit('admin.workspace_updated')
  updateWorkspace(
    @Param('workspaceId') wid: string,
    @Body() dto: AdminUpdateWorkspaceDto,
    @CurrentAdmin() admin: AdminPayload,
  ) {
    return this.adminService.updateWorkspace(wid, dto, admin.id);
  }

  @Post('workspaces/:workspaceId/impersonate')
  @Audit('admin.impersonation_started')
  impersonate(
    @Param('workspaceId') wid: string,
    @Body() dto: ImpersonateDto, // { userId?, reason: string (REQUIRED) }
    @CurrentAdmin() admin: AdminPayload,
  ) {
    return this.impersonationService.createSession(admin.id, wid, dto);
  }

  @Delete('impersonation/:token')
  @Audit('admin.impersonation_ended')
  endSession(@Param('token') token: string, @CurrentAdmin() admin: AdminPayload) {
    return this.impersonationService.endSession(token, admin.id);
  }

  @Get('jobs')
  listJobs(@Query() filter: JobLogFilterDto) {
    return this.jobsService.listAll(filter);
  }

  @Post('jobs/:jobId/retry')
  @Audit('admin.job_retried')
  retryJob(@Param('jobId') jobId: string, @CurrentAdmin() admin: AdminPayload) {
    return this.jobsService.retry(jobId, admin.id);
  }

  @Get('jobs/dead-letter')
  deadLetter(@Query() filter: JobLogFilterDto) {
    return this.jobsService.getDeadLetter(filter);
  }

  @Get('audit-logs')
  auditLogs(@Query() filter: AuditFilterDto) {
    return this.auditRepo.findAll(filter); // cross-workspace
  }
}

// Admin endpoints summary:
// GET    /admin/workspaces                    list all
// GET    /admin/workspaces/:id                detail
// PATCH  /admin/workspaces/:id                update (super_admin)
// POST   /admin/workspaces/:id/impersonate    start impersonation
// DELETE /admin/impersonation/:token           end session
// GET    /admin/audit-logs                    cross-workspace
// GET    /admin/jobs                          all job logs
// POST   /admin/jobs/:jobId/retry             retry failed
// GET    /admin/jobs/dead-letter              dead letter queue
// DELETE /admin/jobs/:jobId                   cancel running
// GET    /admin/sso/connections               all SSO
// POST   /admin/sso/connections/:id/test      test connection
```

---

## Impersonation Service

```typescript
@Injectable()
export class ImpersonationService {
  async createSession(adminId: string, workspaceId: string, dto: ImpersonateDto) {
    // Verify admin has impersonation rights
    await this.assertCanImpersonate(adminId, workspaceId);

    const sessionToken = crypto.randomBytes(32).toString('hex');
    const expiresAt = addHours(new Date(), 1); // MAX 1 hour, non-renewable

    const [session] = await this.db.insert(impersonationSessions).values({
      adminId,
      workspaceId,
      impersonatedUserId: dto.userId ?? null,
      reason: dto.reason, // REQUIRED — stored permanently
      sessionToken,
      expiresAt,
    }).returning();

    // SYNCHRONOUS audit — must not be dropped
    await this.auditService.logSync({
      workspaceId,
      actorId: adminId,
      actorType: 'admin',
      action: 'admin.impersonation_started',
      metadata: {
        reason: dto.reason,
        targetUserId: dto.userId,
        expiresAt: expiresAt.toISOString(),
      },
    });

    return { sessionToken, expiresAt };
  }

  async validateSession(token: string): Promise<ImpersonationSession> {
    const session = await this.db.query.impersonationSessions.findFirst({
      where: and(
        eq(impersonationSessions.sessionToken, token),
        gt(impersonationSessions.expiresAt, new Date()),
        isNull(impersonationSessions.endedAt),
      ),
    });
    if (!session) throw new UnauthorizedException('Invalid or expired impersonation session');
    return session;
  }

  async endSession(token: string, adminId: string) {
    await this.db.update(impersonationSessions)
      .set({ endedAt: new Date() })
      .where(and(
        eq(impersonationSessions.sessionToken, token),
        eq(impersonationSessions.adminId, adminId),
      ));
    await this.auditService.logSync({
      actorId: adminId,
      actorType: 'admin',
      action: 'admin.impersonation_ended',
    });
  }
}

// ImpersonationGuard — detects impersonation header, marks request
@Injectable()
export class ImpersonationGuard implements CanActivate {
  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const impToken = req.headers['x-impersonation-token'];
    if (!impToken) return true;

    const session = await this.impersonationService.validateSession(impToken);
    req.isImpersonating = true;
    req.impersonationSession = session;
    // All audit logs in this request → actorType: 'admin_impersonation'
    return true;
  }
}
```

---

## SSO Flow

End-to-end flow for Microsoft AD (applies pattern to all providers):

```
1. Admin enables SSO:
   POST /workspaces/:id/sso/connections
   → Validate plan (SSO = enterprise only via PlanStrategy.canUseSSO())
   → Insert sso_connections row with clientId, clientSecret, tenantId
   → Audit: sso.connection_created

2. Test connection:
   POST /admin/sso/connections/:id/test
   → IdentityManager.forProvider('microsoft_ad').getAuthorizationUrl()
   → Return test redirect URL

3. User login via SSO:
   GET /workspaces/:id/sso/login
   → Fetch active connection for workspace
   → MicrosoftAdAdapter.getAuthorizationUrl(conn, state)
   → Redirect user to Microsoft login

4. OAuth callback:
   GET /auth/sso/callback?code=xxx&state=yyy
   → MicrosoftAdAdapter.exchangeCodeForTokens(conn, code)
   → Store encrypted tokens in sso_connections
   → MicrosoftAdAdapter.getUserProfile(accessToken)
   → Find or create user in workspace
   → Issue JWT
   → Audit: sso.user_authenticated

5. Directory sync (background):
   POST /workspaces/:id/sso/sync
   → Check dedup: active_job:{workspaceId}:identity-sync
   → Enqueue BullMQ job
   → Return { jobId }

6. IdentitySyncProcessor extends BaseProcessor:
   → MicrosoftAdAdapter.syncDirectory(conn, workspaceId)
   → Paginate Graph API to completion
   → Batch upsert users (NOT loop insert)
   → Update job progress in Redis
   → BaseProcessor.finally() writes job_logs

7. Progress:
   GET /workspaces/:id/jobs/:jobId/progress (SSE)
   → Stream from Redis job:{jobId}:progress

8. On failure:
   → BaseProcessor writes failed status to job_logs
   → Final attempt → dead letter queue
   → Admin sees in GET /admin/jobs/dead-letter
   → Admin retries via POST /admin/jobs/:jobId/retry
```

---

## File Import Flow

```
1. Request upload URL:
   POST /domains/:domainId/recipients/imports/upload-url
   → Create importJobs row (status: 'pending')
   → Generate presigned S3 URL
   → Return { jobId, uploadUrl }

2. Frontend uploads directly to S3

3. Start processing:
   POST /domains/:domainId/recipients/imports/:jobId/process
   → Enqueue BullMQ job
   → Return { status: 'validating' }

4. ImportValidationProcessor extends BaseProcessor:
   → Download file from S3
   → Parse CSV/XLSX (use papaparse or exceljs)
   → For each row:
     - Insert into import_staging_rows with rawData
     - Validate against custom_field_definitions (from Redis cache)
     - Map columns to fields
     - Set status: 'valid' or 'error' with error details
   → Update importJobs: totalRows, validRows, errorRows
   → Set status: 'preview'
   → Update Redis progress throughout

5. Preview:
   GET /domains/:domainId/recipients/imports/:jobId/preview
   → Return { validRows, errorRows, sampleData (first 10 valid), sampleErrors (first 10 errors) }
   → User reviews before committing

6. Commit:
   POST /domains/:domainId/recipients/imports/:jobId/commit
   → Enqueue ImportCommitProcessor
   → Return { status: 'processing' }

7. ImportCommitProcessor extends BaseProcessor:
   → SELECT valid rows from staging in batches of 500
   → INSERT INTO recipients (with company_id, workspace_id, domain_id from tenantContext)
   → Handle duplicates: ON CONFLICT (domain_id, email) DO UPDATE
   → Delete staging rows after commit
   → Update importJobs: status 'done', processedRows
   → Redis progress throughout

8. SSE progress available at:
   GET /domains/:domainId/jobs/:jobId/progress
```

---

## Domain Migration Handler

Rare (~once/year). Runs as background job.

```typescript
// Service
async migrateDomain(domainId: string, newWorkspaceId: string, adminId: string) {
  const newWorkspace = await this.workspaceRepo.findById(newWorkspaceId);
  const newCompanyId = newWorkspace.companyId;
  const oldDomain = await this.domainRepo.findById(domainId);

  await this.auditService.logSync({
    domainId,
    actorId: adminId,
    actorType: 'admin',
    action: 'admin.domain_migration_started',
    metadata: {
      fromWorkspaceId: oldDomain.workspaceId,
      toWorkspaceId: newWorkspaceId,
      fromCompanyId: oldDomain.companyId,
      toCompanyId: newCompanyId,
    },
  });

  await this.queue.add('domain-migration', {
    domainId,
    oldWorkspaceId: oldDomain.workspaceId,
    newWorkspaceId,
    oldCompanyId: oldDomain.companyId,
    newCompanyId,
    tables: [
      'recipients', 'email_recipients', 'sms_recipients',
      'whatsapp_recipients', 'push_recipients',
      // ... all extension tables
    ],
  });
}

// Processor
@Processor('admin-ops')
export class DomainMigrationProcessor extends BaseProcessor {
  async processJob(job: Job) {
    const { domainId, newWorkspaceId, newCompanyId, tables } = job.data;

    // 1. Update domain record itself
    await this.db.update(domains)
      .set({ workspaceId: newWorkspaceId, companyId: newCompanyId })
      .where(eq(domains.id, domainId));

    // 2. Update each data table
    for (const tableName of tables) {
      await this.db.execute(sql`
        UPDATE ${sql.identifier(tableName)}
        SET workspace_id = ${newWorkspaceId}, company_id = ${newCompanyId}
        WHERE domain_id = ${domainId}
      `);
    }

    // 3. Invalidate all Redis caches
    await this.redis.del(`domain:${domainId}:context`);
    await this.redis.del(`workspace:${job.data.oldWorkspaceId}:custom_field_defs`);
    // Invalidate any cached filter results for this domain
    const filterKeys = await this.redis.keys(`domain:${domainId}:filter:*`);
    if (filterKeys.length) await this.redis.del(...filterKeys);
  }
}
```

---

## BullMQ Queue Configuration

```typescript
BullModule.registerQueue(
  {
    name: 'recipients',
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: 'exponential', delay: 2000 },
      removeOnComplete: { age: 86400, count: 1000 },
      removeOnFail: false, // keep ALL failed for inspection
    },
  },
  {
    name: 'imports',
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: 'exponential', delay: 5000 },
      removeOnFail: false,
    },
  },
  {
    name: 'identity-sync',
    defaultJobOptions: {
      attempts: 5,
      backoff: { type: 'exponential', delay: 10000 },
      removeOnFail: false,
    },
  },
  {
    name: 'admin-ops',
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: 'exponential', delay: 5000 },
      removeOnFail: false,
    },
  },
  {
    name: 'dead-letter',
    defaultJobOptions: {
      attempts: 1,
      removeOnComplete: false,
      removeOnFail: false,
    },
  },
)

// SSE Progress Controller (reusable across all modules)
@Controller('domains/:domainId/jobs')
@UseGuards(JwtAuthGuard, TenantContextGuard)
export class JobProgressController {
  @Get(':jobId/progress')
  @Sse()
  progress(
    @Param('domainId') domainId: string,
    @Param('jobId') jobId: string,
  ): Observable<MessageEvent> {
    return interval(500).pipe(
      switchMap(async () => {
        const raw = await this.redis.get(`job:${jobId}:progress`);
        return { data: raw ?? JSON.stringify({ status: 'pending' }) } as MessageEvent;
      }),
      takeWhile((e: any) => {
        const data = JSON.parse(e.data);
        return !['completed', 'done', 'failed'].includes(data.status);
      }, true),
    );
  }
}
```
