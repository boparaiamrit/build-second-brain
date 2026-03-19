---
name: testing-skill
description: Exhaustive testing patterns for multi-tenant SaaS — unit tests (Vitest), integration tests, E2E tests (Playwright), multi-tenant isolation tests, negative security tests, test data factories, and CI integration. Covers both NestJS backend and Next.js frontend. Trigger when writing tests, setting up test infrastructure, reviewing test coverage, or asking about testing strategies for multi-tenant applications.
---

# SKILL: Exhaustive Testing for Multi-Tenant SaaS

## Stack Under Test

| Layer | Technology | Test Runner |
|-------|-----------|------------|
| Backend API | NestJS + Prisma/Drizzle + PostgreSQL + BullMQ + Redis | Vitest |
| Frontend UI | Next.js 16 + React 19 + TanStack Query + Zustand + TanStack Table | Vitest + Testing Library |
| End-to-End | Full stack | Playwright |
| Multi-tenant isolation | API + DB | Vitest + supertest |

---

## IDENTITY

You are a senior test engineer specializing in multi-tenant SaaS platforms. You:

1. Treat tests as the primary documentation of system behavior
2. Prioritize isolation tests above all else — a data leak is worse than a broken feature
3. Never trust "it works on my machine" — automated tests in CI or it does not exist
4. Write tests that catch real bugs, not tests that pad coverage numbers
5. Design test data factories that mirror the production tenant hierarchy

---

## TESTING PYRAMID — MEMORIZE THIS

```
                    ┌───────────┐
                    │    E2E    │  ~10% — Happy paths, critical user journeys
                    │(Playwright)│  Auth flow, workspace switch, import wizard
                    ├───────────┤
                    │ Integration│  ~30% — API endpoints, DB queries, job processors
                    │(Vitest+DB) │  Multi-tenant isolation, BullMQ flows, SSE
                    ├───────────┤
                    │   Unit     │  ~60% — Services, utils, Zod schemas, hooks, stores
                    │ (Vitest)   │  Fast, mocked dependencies, deterministic
                    └───────────┘
```

### Fourth Layer: Isolation Tests (Cuts Across All Three)

Isolation tests verify that workspace A cannot see workspace B data. They run at integration level (real DB) but are so critical they get their own category, dedicated files, and mandatory CI gate.

```
ANY module shipped without isolation tests = BLOCKED from merge.
```

---

## WHEN TO WRITE EACH TEST TYPE

### Unit Tests — ALWAYS

Write unit tests for:
- Every service method (business logic)
- Every utility/helper function
- Every Zod schema (valid + invalid inputs)
- Every React hook (TanStack Query wrappers, Zustand stores)
- Every pure component (rendering, conditional UI)

**Do NOT unit test:**
- Controllers (test at integration level with supertest)
- Repository methods (test at integration level with real DB)
- CSS/styling (test visually with Playwright screenshots)

### Integration Tests — For Every API Endpoint

Write integration tests for:
- Every controller endpoint (HTTP method + route + response shape)
- Every repository method (real DB, real queries)
- Every BullMQ processor (real job execution, mock external APIs)
- Every guard/middleware (TenantContextGuard, auth guards)
- **Every endpoint's workspace boundary** (isolation test)

### E2E Tests — For Every User Journey

Write E2E tests for:
- Authentication flow (login, session persistence, logout)
- Workspace switching (context changes, data refreshes)
- CRUD operations (create, read, update, delete via UI)
- Data table interactions (search, filter, sort, bulk select, pagination)
- Import wizard (upload, map, review, commit)
- Settings changes (inheritance, override, reset)

### Isolation Tests — For Every Data-Touching Endpoint

Write isolation tests for:
- Every GET endpoint (must not return cross-workspace data)
- Every POST/PATCH/DELETE endpoint (must not mutate cross-workspace data)
- Every bulk operation (must not touch cross-workspace records)
- Every aggregation/report (must scope to correct tenant level)
- Every search/filter (must not leak cross-tenant results)

---

## BACKEND TESTING PATTERNS

### Test File Organization

```
src/modules/{feature}/
  ├── __tests__/
  │   ├── {feature}.service.spec.ts        # Unit tests — mocked repo
  │   ├── {feature}.controller.spec.ts     # Integration — supertest + real DB
  │   ├── {feature}.repository.spec.ts     # Integration — real DB
  │   ├── {feature}.processor.spec.ts      # BullMQ job tests
  │   └── {feature}.isolation.spec.ts      # Multi-tenant isolation
  ├── {feature}.module.ts
  ├── {feature}.controller.ts
  ├── {feature}.service.ts
  ├── {feature}.repository.ts
  └── {feature}.processor.ts
```

### NestJS Service Test Template (Unit)

```typescript
import { Test } from '@nestjs/testing';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { RecipientsService } from '../recipients.service';
import { RecipientsRepository } from '../recipients.repository';
import { AuditService } from '../../audit/audit.service';
import { PlanManager } from '../../billing/plan.manager';

describe('RecipientsService', () => {
  let service: RecipientsService;
  let repo: RecipientsRepository;
  let auditService: AuditService;

  const mockTenantContext = {
    domainId: 'domain-1',
    workspaceId: 'ws-1',
    companyId: 'company-1',
    subscriptionTier: 'pro' as const,
    subscriptionStatus: 'active' as const,
    seatsLimit: 10,
    recipientLimit: 50_000,
  };

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      providers: [
        RecipientsService,
        {
          provide: RecipientsRepository,
          useValue: {
            findMany: vi.fn(),
            findById: vi.fn(),
            create: vi.fn(),
            update: vi.fn(),
            softDelete: vi.fn(),
            countByCompany: vi.fn(),
          },
        },
        {
          provide: AuditService,
          useValue: { log: vi.fn(), logSync: vi.fn() },
        },
        {
          provide: PlanManager,
          useValue: {
            forTier: vi.fn().mockReturnValue({
              maxRecipientsPerImport: () => 50_000,
              maxCustomFields: () => 50,
            }),
          },
        },
      ],
    }).compile();

    service = module.get(RecipientsService);
    repo = module.get(RecipientsRepository);
    auditService = module.get(AuditService);
  });

  describe('create', () => {
    it('should create a recipient when under limit', async () => {
      vi.mocked(repo.countByCompany).mockResolvedValue(100);
      vi.mocked(repo.create).mockResolvedValue({ id: 'r-1', email: 'a@test.com' });

      const result = await service.create(mockTenantContext, {
        email: 'a@test.com',
        firstName: 'Test',
        lastName: 'User',
      });

      expect(result).toEqual({ id: 'r-1', email: 'a@test.com' });
      expect(repo.create).toHaveBeenCalledWith(
        expect.objectContaining({
          domainId: 'domain-1',
          workspaceId: 'ws-1',
          companyId: 'company-1',
        }),
      );
    });

    it('should throw PaymentRequiredException when recipient limit exceeded', async () => {
      vi.mocked(repo.countByCompany).mockResolvedValue(50_000);

      await expect(
        service.create(mockTenantContext, { email: 'a@test.com', firstName: 'A', lastName: 'B' }),
      ).rejects.toThrow('Would exceed recipient limit');
    });

    it('should log audit event on successful creation', async () => {
      vi.mocked(repo.countByCompany).mockResolvedValue(100);
      vi.mocked(repo.create).mockResolvedValue({ id: 'r-1', email: 'a@test.com' });

      await service.create(mockTenantContext, { email: 'a@test.com', firstName: 'A', lastName: 'B' });

      expect(auditService.log).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'recipient.created',
          workspaceId: 'ws-1',
        }),
      );
    });
  });

  describe('bulkDelete', () => {
    it('should delete only IDs belonging to the domain', async () => {
      vi.mocked(repo.softDelete).mockResolvedValue({ affected: 2 });

      const result = await service.bulkDelete(mockTenantContext, ['r-1', 'r-2', 'r-3']);

      expect(repo.softDelete).toHaveBeenCalledWith('domain-1', ['r-1', 'r-2', 'r-3']);
    });
  });
});
```

### NestJS Controller Test Template (Integration)

```typescript
import { Test } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import * as request from 'supertest';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { AppModule } from '../../../app.module';
import { TestDbHelper } from '../../../../test/helpers/test-db';
import { createTestTenant } from '../../../../test/factories/tenant.factory';

describe('RecipientsController (Integration)', () => {
  let app: INestApplication;
  let db: TestDbHelper;
  let tenant: Awaited<ReturnType<typeof createTestTenant>>;

  beforeAll(async () => {
    const module = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = module.createNestApplication();
    await app.init();

    db = new TestDbHelper(module);
    tenant = await createTestTenant(db);
  });

  afterAll(async () => {
    await db.cleanup();
    await app.close();
  });

  describe('GET /domains/:domainId/recipients', () => {
    it('should return 200 with paginated recipients', async () => {
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'alice@test.com',
      });

      const res = await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(200);

      expect(res.body.data).toHaveLength(1);
      expect(res.body.data[0].email).toBe('alice@test.com');
      expect(res.body.meta).toMatchObject({
        total: 1,
        page: 1,
        pageSize: expect.any(Number),
      });
    });

    it('should return 401 without auth token', async () => {
      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients`)
        .expect(401);
    });

    it('should return empty array for domain with no data', async () => {
      const emptyDomain = await db.createDomain(tenant.workspaceA.id, tenant.company.id);

      const res = await request(app.getHttpServer())
        .get(`/domains/${emptyDomain.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(200);

      expect(res.body.data).toHaveLength(0);
    });
  });

  describe('POST /domains/:domainId/recipients', () => {
    it('should create recipient with all tenant IDs', async () => {
      const res = await request(app.getHttpServer())
        .post(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .send({ email: 'new@test.com', firstName: 'New', lastName: 'User' })
        .expect(201);

      expect(res.body.data).toMatchObject({
        email: 'new@test.com',
        domainId: tenant.domainA.id,
        workspaceId: tenant.workspaceA.id,
        companyId: tenant.company.id,
      });
    });

    it('should reject invalid email', async () => {
      await request(app.getHttpServer())
        .post(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .send({ email: 'not-an-email', firstName: 'Bad', lastName: 'Input' })
        .expect(400);
    });

    it('should reject duplicate email within same domain', async () => {
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'dup@test.com',
      });

      await request(app.getHttpServer())
        .post(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .send({ email: 'dup@test.com', firstName: 'Dup', lastName: 'User' })
        .expect(409);
    });
  });
});
```

### Repository Test Template (Integration with Real DB)

```typescript
import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { TestDbHelper } from '../../../../test/helpers/test-db';
import { RecipientsRepository } from '../recipients.repository';
import { createTestTenant } from '../../../../test/factories/tenant.factory';

describe('RecipientsRepository', () => {
  let db: TestDbHelper;
  let repo: RecipientsRepository;
  let tenant: Awaited<ReturnType<typeof createTestTenant>>;

  beforeAll(async () => {
    db = await TestDbHelper.create();
    repo = new RecipientsRepository(db.drizzle);
    tenant = await createTestTenant(db);
  });

  beforeEach(async () => {
    await db.truncate('recipients');
  });

  afterAll(async () => {
    await db.cleanup();
  });

  describe('findMany', () => {
    it('should return only recipients for the specified domain', async () => {
      // Seed data in two domains
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'alice@domainA.com',
      });
      await db.createRecipient(tenant.domainB.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'bob@domainB.com',
      });

      const result = await repo.findMany(tenant.domainA.id, {});

      expect(result.rows).toHaveLength(1);
      expect(result.rows[0].email).toBe('alice@domainA.com');
    });

    it('should filter by status', async () => {
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'active@test.com',
        status: 'active',
      });
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'bounced@test.com',
        status: 'bounced',
      });

      const result = await repo.findMany(tenant.domainA.id, { status: 'active' });

      expect(result.rows).toHaveLength(1);
      expect(result.rows[0].email).toBe('active@test.com');
    });

    it('should paginate with limit and offset', async () => {
      for (let i = 0; i < 10; i++) {
        await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
          email: `user${i}@test.com`,
        });
      }

      const result = await repo.findMany(tenant.domainA.id, { limit: 3, offset: 0 });

      expect(result.rows).toHaveLength(3);
      expect(result.total).toBe(10);
    });

    it('should search by email pattern', async () => {
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'rajesh@tatasteel.com',
      });
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'priya@tatasteel.com',
      });

      const result = await repo.findMany(tenant.domainA.id, { search: 'rajesh' });

      expect(result.rows).toHaveLength(1);
      expect(result.rows[0].email).toBe('rajesh@tatasteel.com');
    });
  });

  describe('countByCompany', () => {
    it('should count all recipients across all domains in a company', async () => {
      await db.createRecipient(tenant.domainA.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'a@test.com',
      });
      await db.createRecipient(tenant.domainB.id, tenant.workspaceA.id, tenant.company.id, {
        email: 'b@test.com',
      });

      const count = await repo.countByCompany(tenant.company.id);

      expect(count).toBe(2);
    });
  });
});
```

### BullMQ Job Processor Test Template

```typescript
import { Test } from '@nestjs/testing';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { Job } from 'bullmq';
import { BulkUpdateProcessor } from '../bulk-update.processor';
import { RecipientsRepository } from '../recipients.repository';
import { JobLogRepository } from '../../job-logs/job-log.repository';

describe('BulkUpdateProcessor', () => {
  let processor: BulkUpdateProcessor;
  let repo: RecipientsRepository;
  let redis: { set: ReturnType<typeof vi.fn>; get: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    redis = { set: vi.fn(), get: vi.fn() };

    const module = await Test.createTestingModule({
      providers: [
        BulkUpdateProcessor,
        {
          provide: RecipientsRepository,
          useValue: {
            countByFilter: vi.fn(),
            batchUpdate: vi.fn(),
          },
        },
        {
          provide: JobLogRepository,
          useValue: { record: vi.fn() },
        },
        { provide: 'REDIS', useValue: redis },
        { provide: 'BullQueue_dead-letter', useValue: { add: vi.fn() } },
      ],
    }).compile();

    processor = module.get(BulkUpdateProcessor);
    repo = module.get(RecipientsRepository);
  });

  it('should process all records in batches of 500', async () => {
    vi.mocked(repo.countByFilter).mockResolvedValue(1200);
    vi.mocked(repo.batchUpdate).mockResolvedValue(undefined);

    const job = {
      id: 'job-1',
      data: {
        domainId: 'domain-1',
        filter: { status: 'active' },
        updates: { department: 'Engineering' },
        tenantContext: { companyId: 'c-1', workspaceId: 'ws-1' },
      },
      opts: { attempts: 3 },
      attemptsMade: 0,
      queueName: 'recipients',
      name: 'bulk-update',
    } as unknown as Job;

    await processor.processJob(job);

    // 1200 records / 500 batch = 3 batches (500 + 500 + 200)
    expect(repo.batchUpdate).toHaveBeenCalledTimes(3);
  });

  it('should update Redis progress on each batch', async () => {
    vi.mocked(repo.countByFilter).mockResolvedValue(1000);
    vi.mocked(repo.batchUpdate).mockResolvedValue(undefined);

    const job = {
      id: 'job-1',
      data: {
        domainId: 'domain-1',
        filter: {},
        updates: { status: 'inactive' },
        tenantContext: { companyId: 'c-1', workspaceId: 'ws-1' },
      },
      opts: { attempts: 3 },
      attemptsMade: 0,
      queueName: 'recipients',
      name: 'bulk-update',
    } as unknown as Job;

    await processor.processJob(job);

    // Progress updated on each batch + final completion
    expect(redis.set).toHaveBeenCalledWith(
      'job:job-1:progress',
      expect.stringContaining('"status":"completed"'),
      'EX',
      3600,
    );
  });

  it('should throw and let BaseProcessor handle dead letter on final attempt', async () => {
    vi.mocked(repo.countByFilter).mockRejectedValue(new Error('DB connection failed'));

    const job = {
      id: 'job-1',
      data: {
        domainId: 'domain-1',
        filter: {},
        updates: {},
        tenantContext: { companyId: 'c-1', workspaceId: 'ws-1' },
      },
      opts: { attempts: 3 },
      attemptsMade: 2,
      queueName: 'recipients',
      name: 'bulk-update',
    } as unknown as Job;

    await expect(processor.processJob(job)).rejects.toThrow('DB connection failed');
  });
});
```

---

## FRONTEND TESTING PATTERNS

### React Component Test Template (Testing Library)

```typescript
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RecipientForm } from '../recipient-form';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('RecipientForm', () => {
  it('should render all form fields', () => {
    render(<RecipientForm onSubmit={vi.fn()} />, { wrapper: createWrapper() });

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save|create|submit/i })).toBeInTheDocument();
  });

  it('should show validation errors for empty required fields', async () => {
    const user = userEvent.setup();
    render(<RecipientForm onSubmit={vi.fn()} />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /save|create|submit/i }));

    expect(await screen.findByText(/email is required|invalid email/i)).toBeInTheDocument();
  });

  it('should call onSubmit with valid data', async () => {
    const handleSubmit = vi.fn();
    const user = userEvent.setup();
    render(<RecipientForm onSubmit={handleSubmit} />, { wrapper: createWrapper() });

    await user.type(screen.getByLabelText(/email/i), 'rajesh@tatasteel.com');
    await user.type(screen.getByLabelText(/first name/i), 'Rajesh');
    await user.type(screen.getByLabelText(/last name/i), 'Kumar');
    await user.click(screen.getByRole('button', { name: /save|create|submit/i }));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        email: 'rajesh@tatasteel.com',
        firstName: 'Rajesh',
        lastName: 'Kumar',
      }),
    );
  });

  it('should disable submit button while submitting', async () => {
    const user = userEvent.setup();
    render(<RecipientForm onSubmit={vi.fn()} isSubmitting />, { wrapper: createWrapper() });

    expect(screen.getByRole('button', { name: /save|create|submit/i })).toBeDisabled();
  });
});
```

### React Hook Test Template (TanStack Query)

```typescript
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useRecipients, useCreateRecipient } from '../hooks/use-recipients';
import { recipientsApi } from '../lib/api';

vi.mock('../lib/api');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useRecipients', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should fetch recipients and return data', async () => {
    vi.mocked(recipientsApi.list).mockResolvedValue([
      { id: '1', email: 'a@test.com', firstName: 'Alice', lastName: 'K' },
    ]);

    const { result } = renderHook(() => useRecipients(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data![0].email).toBe('a@test.com');
  });

  it('should pass filter params to API', async () => {
    vi.mocked(recipientsApi.list).mockResolvedValue([]);

    const filter = { status: ['active'], search: 'raj' };
    renderHook(() => useRecipients(filter), { wrapper: createWrapper() });

    await waitFor(() => expect(recipientsApi.list).toHaveBeenCalledWith(filter));
  });

  it('should handle API error gracefully', async () => {
    vi.mocked(recipientsApi.list).mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useRecipients(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('Network error');
  });
});

describe('useCreateRecipient', () => {
  it('should invalidate list queries on success', async () => {
    vi.mocked(recipientsApi.create).mockResolvedValue({
      id: 'new-1',
      email: 'new@test.com',
      firstName: 'New',
      lastName: 'User',
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useCreateRecipient(), { wrapper });

    result.current.mutate({ email: 'new@test.com', firstName: 'New', lastName: 'User' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: expect.arrayContaining(['recipients']) }),
    );
  });
});
```

### Zustand Store Test Template

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkspaceStore } from '../workspace-store';

describe('WorkspaceStore', () => {
  beforeEach(() => {
    // Reset store state between tests
    useWorkspaceStore.setState({
      activeWorkspaceId: null,
      activeCompanyId: null,
      workspaces: [],
    });
  });

  it('should set active workspace', () => {
    const store = useWorkspaceStore.getState();
    store.setActiveWorkspace('ws-1');
    expect(useWorkspaceStore.getState().activeWorkspaceId).toBe('ws-1');
  });

  it('should clear active workspace on company switch', () => {
    useWorkspaceStore.setState({ activeWorkspaceId: 'ws-1', activeCompanyId: 'c-1' });

    const store = useWorkspaceStore.getState();
    store.setActiveCompany('c-2');

    expect(useWorkspaceStore.getState().activeWorkspaceId).toBeNull();
    expect(useWorkspaceStore.getState().activeCompanyId).toBe('c-2');
  });

  it('should return workspace count for progressive complexity', () => {
    useWorkspaceStore.setState({
      workspaces: [
        { id: 'ws-1', name: 'Tata Steel', companyId: 'c-1' },
        { id: 'ws-2', name: 'Tata Motors', companyId: 'c-1' },
      ],
    });

    const store = useWorkspaceStore.getState();
    expect(store.workspaces.length).toBe(2);
    // UC3 features should be visible
  });
});
```

### Zod Schema Test Template

```typescript
import { describe, it, expect } from 'vitest';
import { CreateRecipientSchema, RecipientFilterSchema } from '../types';

describe('CreateRecipientSchema', () => {
  it('should accept valid input', () => {
    const result = CreateRecipientSchema.safeParse({
      email: 'rajesh@tatasteel.com',
      firstName: 'Rajesh',
      lastName: 'Kumar',
      status: 'active',
    });
    expect(result.success).toBe(true);
  });

  it('should reject invalid email', () => {
    const result = CreateRecipientSchema.safeParse({
      email: 'not-email',
      firstName: 'Test',
      lastName: 'User',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain('email');
    }
  });

  it('should reject empty firstName', () => {
    const result = CreateRecipientSchema.safeParse({
      email: 'test@test.com',
      firstName: '',
      lastName: 'User',
    });
    expect(result.success).toBe(false);
  });

  it('should apply default status when not provided', () => {
    const result = CreateRecipientSchema.parse({
      email: 'test@test.com',
      firstName: 'Test',
      lastName: 'User',
    });
    expect(result.status).toBe('active');
  });
});

describe('RecipientFilterSchema', () => {
  it('should accept empty filter (all defaults)', () => {
    const result = RecipientFilterSchema.safeParse({});
    expect(result.success).toBe(true);
  });

  it('should coerce page/limit to numbers', () => {
    const result = RecipientFilterSchema.parse({ page: '2', limit: '25' });
    expect(result.page).toBe(2);
    expect(result.limit).toBe(25);
  });

  it('should reject negative page numbers', () => {
    const result = RecipientFilterSchema.safeParse({ page: -1 });
    expect(result.success).toBe(false);
  });
});
```

---

## TEST DATA FACTORIES

### Tenant Hierarchy Factory

```typescript
// test/factories/tenant.factory.ts
import { TestDbHelper } from '../helpers/test-db';
import { randomUUID } from 'crypto';

interface TestTenant {
  company: { id: string; name: string; slug: string };
  workspaceA: { id: string; name: string; companyId: string };
  workspaceB: { id: string; name: string; companyId: string };
  domainA: { id: string; domainName: string; workspaceId: string; companyId: string };
  domainB: { id: string; domainName: string; workspaceId: string; companyId: string };
  domainC: { id: string; domainName: string; workspaceId: string; companyId: string };
  tokenA: string; // JWT for workspace A admin
  tokenB: string; // JWT for workspace B admin
  companyToken: string; // JWT for company admin
}

/**
 * Creates a full multi-tenant test hierarchy:
 * Company (Tata Group)
 *   ├── Workspace A (Tata Steel) with Domain A (tatasteel.com)
 *   └── Workspace B (Tata Motors) with Domain B (tatamotors.com) + Domain C (tatamotors.co.in)
 */
export async function createTestTenant(db: TestDbHelper): Promise<TestTenant> {
  const company = await db.createCompany({
    name: 'Tata Group',
    slug: `tata-group-${randomUUID().slice(0, 8)}`,
    subscriptionTier: 'enterprise',
    subscriptionStatus: 'active',
    recipientLimit: 100_000,
  });

  const workspaceA = await db.createWorkspace(company.id, {
    name: 'Tata Steel',
    slug: 'tata-steel',
  });

  const workspaceB = await db.createWorkspace(company.id, {
    name: 'Tata Motors',
    slug: 'tata-motors',
  });

  const domainA = await db.createDomain(workspaceA.id, company.id, {
    domainName: 'tatasteel.com',
    verified: true,
  });

  const domainB = await db.createDomain(workspaceB.id, company.id, {
    domainName: 'tatamotors.com',
    verified: true,
  });

  const domainC = await db.createDomain(workspaceB.id, company.id, {
    domainName: 'tatamotors.co.in',
    verified: true,
  });

  const tokenA = await db.createAuthToken(workspaceA.id, 'workspace_admin');
  const tokenB = await db.createAuthToken(workspaceB.id, 'workspace_admin');
  const companyToken = await db.createAuthToken(company.id, 'company_admin');

  return {
    company,
    workspaceA,
    workspaceB,
    domainA,
    domainB,
    domainC,
    tokenA,
    tokenB,
    companyToken,
  };
}

/**
 * Creates a simple UC1 tenant (1 company, 1 workspace, 1 domain).
 */
export async function createSimpleTenant(db: TestDbHelper) {
  const company = await db.createCompany({
    name: 'Zerodha',
    slug: `zerodha-${randomUUID().slice(0, 8)}`,
    subscriptionTier: 'pro',
    subscriptionStatus: 'active',
    recipientLimit: 50_000,
  });

  const workspace = await db.createWorkspace(company.id, {
    name: 'Zerodha',
    slug: 'zerodha',
  });

  const domain = await db.createDomain(workspace.id, company.id, {
    domainName: 'zerodha.com',
    verified: true,
  });

  const token = await db.createAuthToken(workspace.id, 'workspace_admin');

  return { company, workspace, domain, token };
}

/**
 * Creates a UC2 tenant (1 workspace, multiple domains — same person across domains).
 */
export async function createMultiDomainTenant(db: TestDbHelper) {
  const company = await db.createCompany({
    name: 'Jio Platforms',
    slug: `jio-${randomUUID().slice(0, 8)}`,
    subscriptionTier: 'business',
    subscriptionStatus: 'active',
    recipientLimit: 100_000,
  });

  const workspace = await db.createWorkspace(company.id, {
    name: 'Jio',
    slug: 'jio',
  });

  const domainJio = await db.createDomain(workspace.id, company.id, {
    domainName: 'jio.com',
    verified: true,
  });

  const domainSaavn = await db.createDomain(workspace.id, company.id, {
    domainName: 'jiosaavn.com',
    verified: true,
  });

  const token = await db.createAuthToken(workspace.id, 'workspace_admin');

  return { company, workspace, domainJio, domainSaavn, token };
}
```

### Recipient Factory

```typescript
// test/factories/recipient.factory.ts
import { TestDbHelper } from '../helpers/test-db';
import { randomUUID } from 'crypto';

const INDIAN_NAMES = [
  { firstName: 'Rajesh', lastName: 'Kumar' },
  { firstName: 'Priya', lastName: 'Sharma' },
  { firstName: 'Vikram', lastName: 'Singh' },
  { firstName: 'Anita', lastName: 'Patel' },
  { firstName: 'Suresh', lastName: 'Reddy' },
  { firstName: 'Meera', lastName: 'Nair' },
  { firstName: 'Arjun', lastName: 'Gupta' },
  { firstName: 'Deepa', lastName: 'Iyer' },
  { firstName: 'Amit', lastName: 'Joshi' },
  { firstName: 'Kavita', lastName: 'Deshmukh' },
];

const DEPARTMENTS = [
  'Engineering', 'Marketing', 'Sales', 'HR',
  'Finance', 'Operations', 'Security', 'IT',
];

interface CreateRecipientOpts {
  email?: string;
  firstName?: string;
  lastName?: string;
  status?: string;
  department?: string;
  customFields?: Record<string, unknown>;
}

export function buildRecipient(
  domainId: string,
  workspaceId: string,
  companyId: string,
  overrides?: CreateRecipientOpts,
) {
  const name = INDIAN_NAMES[Math.floor(Math.random() * INDIAN_NAMES.length)];
  return {
    id: randomUUID(),
    domainId,
    workspaceId,
    companyId,
    email: overrides?.email ?? `${name.firstName.toLowerCase()}@test-${randomUUID().slice(0, 6)}.com`,
    firstName: overrides?.firstName ?? name.firstName,
    lastName: overrides?.lastName ?? name.lastName,
    status: overrides?.status ?? 'active',
    department: overrides?.department ?? DEPARTMENTS[Math.floor(Math.random() * DEPARTMENTS.length)],
    customFields: overrides?.customFields ?? {},
  };
}

/**
 * Batch create N recipients in a domain.
 */
export async function seedRecipients(
  db: TestDbHelper,
  domainId: string,
  workspaceId: string,
  companyId: string,
  count: number,
  overrides?: Partial<CreateRecipientOpts>,
) {
  const recipients = Array.from({ length: count }, (_, i) =>
    buildRecipient(domainId, workspaceId, companyId, {
      email: `user${i}@${domainId.slice(0, 8)}.com`,
      ...overrides,
    }),
  );
  return db.insertMany('recipients', recipients);
}
```

---

## MULTI-TENANT ISOLATION TESTS (THE MOST CRITICAL SECTION)

> See `multi-tenant-testing.md` for the complete isolation test framework, templates,
> and all 6 negative security tests as runnable code.

### Why Isolation Tests Are #1 Priority

A broken feature is a bug. A broken tenant boundary is a **security incident**, a **compliance violation**, and potentially a **company-ending event**. Every endpoint that touches data must prove it cannot leak across tenant boundaries.

### Quick Reference: What Must Be Isolated

| Resource | Isolation Level | Test Pattern |
|----------|----------------|-------------|
| Recipients | Domain (hot path), Workspace (dashboard) | GET returns only same-domain data |
| Campaigns | Workspace | Campaign in WS-A invisible to WS-B admin |
| Training | Workspace | Training targets scoped to workspace |
| Settings | Workspace | WS-A settings independent of WS-B |
| Reports | Company (aggregated), Workspace (scoped) | Company admin sees all; workspace admin sees own |
| Audit logs | Workspace (scoped), Company (admin) | WS-A admin cannot see WS-B audit trail |
| Import jobs | Domain | Import into domain-A does not affect domain-B |
| Bulk operations | Domain + Workspace | Bulk delete in WS-A cannot touch WS-B records |

---

## REACT QUERY TESTING

### QueryClient Test Configuration

```typescript
// test/helpers/query-client.ts
import { QueryClient } from '@tanstack/react-query';

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,          // Don't retry in tests
        gcTime: Infinity,      // Don't garbage collect during test
        staleTime: Infinity,   // Don't refetch automatically
      },
      mutations: {
        retry: false,
      },
    },
    logger: {
      log: console.log,
      warn: console.warn,
      error: () => {},        // Suppress error noise in tests
    },
  });
}

export function createTestWrapper() {
  const queryClient = createTestQueryClient();
  return {
    queryClient,
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  };
}
```

### Testing Mutations with Cache Invalidation

```typescript
it('should invalidate recipient list after successful delete', async () => {
  const { queryClient, wrapper } = createTestWrapper();

  // Pre-populate cache
  queryClient.setQueryData(['recipients', 'list', {}], [
    { id: '1', email: 'a@test.com' },
    { id: '2', email: 'b@test.com' },
  ]);

  vi.mocked(recipientsApi.delete).mockResolvedValue(undefined);

  const { result } = renderHook(() => useDeleteRecipient(), { wrapper });

  result.current.mutate('1');

  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  // Verify cache was invalidated (not just the deleted item)
  const cachedData = queryClient.getQueryData(['recipients', 'list', {}]);
  expect(cachedData).toBeUndefined(); // Invalidated, will refetch
});
```

---

## ZUSTAND STORE TESTING

### Testing Store with Middleware

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useWorkspaceStore } from '../stores/workspace-store';

describe('WorkspaceStore (with persist middleware)', () => {
  beforeEach(() => {
    // Reset Zustand store to initial state
    const { setState } = useWorkspaceStore;
    setState({
      activeWorkspaceId: null,
      activeCompanyId: null,
      workspaces: [],
    }, true); // true = replace state (not merge)
  });

  it('should update active workspace and trigger side effects', () => {
    act(() => {
      useWorkspaceStore.getState().setActiveWorkspace('ws-new');
    });

    const state = useWorkspaceStore.getState();
    expect(state.activeWorkspaceId).toBe('ws-new');
  });

  it('should compute showWorkspaceSelector from workspace count', () => {
    act(() => {
      useWorkspaceStore.setState({
        workspaces: [
          { id: 'ws-1', name: 'WS A', companyId: 'c-1' },
          { id: 'ws-2', name: 'WS B', companyId: 'c-1' },
        ],
      });
    });

    const { workspaces } = useWorkspaceStore.getState();
    const showWorkspaceSelector = workspaces.length > 1;
    expect(showWorkspaceSelector).toBe(true); // UC3 mode
  });

  it('should hide workspace selector for UC1 (single workspace)', () => {
    act(() => {
      useWorkspaceStore.setState({
        workspaces: [{ id: 'ws-1', name: 'Zerodha', companyId: 'c-1' }],
      });
    });

    const { workspaces } = useWorkspaceStore.getState();
    const showWorkspaceSelector = workspaces.length > 1;
    expect(showWorkspaceSelector).toBe(false); // UC1 mode
  });
});
```

---

## PLAYWRIGHT E2E PATTERNS

> See `e2e-testing.md` for complete Playwright setup, page object pattern,
> auth flows, data table E2E, and CI integration.

### Quick Reference: What E2E Tests Cover

| User Journey | File | Priority |
|-------------|------|----------|
| Login + session | `auth.spec.ts` | P0 |
| Workspace switching | `workspace-switch.spec.ts` | P0 |
| Recipient CRUD | `recipients.spec.ts` | P0 |
| Data table (search, filter, sort) | `data-table.spec.ts` | P1 |
| Bulk operations | `bulk-ops.spec.ts` | P1 |
| CSV import wizard | `import-wizard.spec.ts` | P1 |
| Settings (inheritance) | `settings.spec.ts` | P1 |
| Campaign creation | `campaign.spec.ts` | P2 |
| Training assignment | `training.spec.ts` | P2 |

---

## CI INTEGRATION

### Vitest Configuration for NestJS + Next.js

```typescript
// vitest.config.ts (backend)
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    globals: true,
    root: resolve(__dirname),
    include: ['src/**/*.spec.ts'],
    exclude: ['src/**/*.e2e-spec.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      thresholds: {
        branches: 70,
        functions: 70,
        lines: 80,
        statements: 80,
      },
    },
    setupFiles: ['./test/setup.ts'],
    // Test database configuration
    pool: 'forks',       // Isolate test suites
    poolOptions: {
      forks: { maxForks: 4 },
    },
  },
});
```

```typescript
// vitest.config.ts (frontend)
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      thresholds: {
        branches: 60,
        functions: 60,
        lines: 70,
        statements: 70,
      },
    },
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
});
```

### GitHub Actions CI Pipeline

```yaml
# .github/workflows/test.yml
name: Test Suite
on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'pnpm'
      - run: pnpm install --frozen-lockfile
      - name: Backend unit tests
        run: pnpm --filter backend test:unit
      - name: Frontend unit tests
        run: pnpm --filter frontend test:unit
      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: |
            backend/coverage/
            frontend/coverage/

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'pnpm'
      - run: pnpm install --frozen-lockfile
      - name: Run migrations
        run: pnpm --filter backend db:migrate:test
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db
      - name: Integration + Isolation tests
        run: pnpm --filter backend test:integration
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379

  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports: ['5432:5432']
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'pnpm'
      - run: pnpm install --frozen-lockfile
      - name: Install Playwright browsers
        run: pnpm exec playwright install --with-deps chromium
      - name: Run E2E tests
        run: pnpm --filter frontend test:e2e
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379
      - name: Upload Playwright report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: frontend/playwright-report/
```

---

## TEST NAMING CONVENTIONS

### Backend (Vitest)

```
describe('ClassName or ModuleName')
  describe('methodName')
    it('should [expected behavior] when [condition]')
```

**Examples:**
```typescript
describe('RecipientsService')
  describe('create')
    it('should create recipient when under limit')
    it('should throw PaymentRequiredException when limit exceeded')
    it('should log audit event on creation')
  describe('bulkDelete')
    it('should delete only IDs belonging to the domain')
    it('should return affected count')
    it('should enqueue BullMQ job when count exceeds 1000')
```

### Frontend (Vitest + Testing Library)

```
describe('ComponentName or HookName')
  it('should render [element] when [condition]')
  it('should call [handler] when [user action]')
  it('should show [feedback] after [mutation]')
```

### E2E (Playwright)

```
test.describe('Feature or User Journey')
  test('should [complete action] as [role]')
```

---

## MOCK PATTERNS: WHEN TO MOCK, WHEN NOT TO

### Mock These (Unit Tests)
- Database repositories
- External API clients (email senders, storage, SSO providers)
- Redis client
- BullMQ queues
- AuditService (fire-and-forget behavior is hard to assert otherwise)
- `Date.now()` / `randomUUID()` when deterministic output matters

### Do NOT Mock These (Use Real Implementations)
- Zod schemas (test validation logic directly)
- Utility/helper functions (they are pure — no side effects)
- TanStack Query hooks (wrap in QueryClientProvider, mock the API layer)
- Zustand stores (test directly, they are synchronous)
- NestJS guards (test at integration level with real guard chain)

### Mock Boundary Rule

```
Unit test:  mock at the REPOSITORY boundary
Integration test: mock at the EXTERNAL SERVICE boundary (real DB, real Redis)
E2E test: mock NOTHING (full stack, real DB, real Redis, real queues)
```

---

## MASTER CHECKLIST — Run Before Shipping Any Feature

### Unit Tests
- [ ] Every service method has >=1 happy path + >=1 error path test
- [ ] Every Zod schema tested with valid + invalid inputs
- [ ] Every React hook tested with QueryClientProvider wrapper
- [ ] Every Zustand store action tested
- [ ] Mocks are at repository boundary (not deeper, not shallower)
- [ ] No `any` types in test files
- [ ] Test names follow `should [behavior] when [condition]` pattern

### Integration Tests
- [ ] Every controller endpoint tested (status code + response shape)
- [ ] Auth required: 401 without token
- [ ] Validation: 400 for invalid input
- [ ] Not found: 404 for missing resource
- [ ] Conflict: 409 for duplicates
- [ ] Real database used (test container or CI service)
- [ ] Data cleaned up after each test (truncate or transaction rollback)

### Multi-Tenant Isolation (MANDATORY)
- [ ] Every GET endpoint: WS-A token cannot fetch WS-B data
- [ ] Every POST endpoint: cannot create data in wrong workspace
- [ ] Every PATCH endpoint: cannot update data in wrong workspace
- [ ] Every DELETE endpoint: cannot delete data in wrong workspace
- [ ] Bulk operations: cannot touch cross-workspace records
- [ ] Company endpoints: aggregate correctly, do not leak individual workspace data
- [ ] Domain-level: domain-A query returns zero domain-B recipients

### E2E Tests
- [ ] Auth flow: login, session persist, logout
- [ ] Workspace switch: data refreshes, no stale data visible
- [ ] CRUD: create, edit, delete via UI — verify in data table
- [ ] Data table: search works, filters work, sort works
- [ ] Bulk actions: select multiple, execute, verify result
- [ ] Import: upload CSV, map columns, review, commit
- [ ] Progressive complexity: UC1 user sees no multi-tenant UI

### CI Pipeline
- [ ] Unit tests pass in <2 minutes
- [ ] Integration tests pass with real DB (postgres service in CI)
- [ ] E2E tests pass with Playwright (artifacts uploaded on failure)
- [ ] Coverage thresholds enforced (80% backend, 70% frontend)
- [ ] Isolation tests are a separate CI step that blocks merge on failure
