# Unit Testing Reference — Vitest for NestJS + Next.js

> Read this file when writing unit tests for backend services, frontend components,
> React hooks, Zustand stores, or Zod schemas.

---

## Table of Contents
1. [Vitest Configuration](#vitest-configuration)
2. [NestJS Service Test Template](#nestjs-service-test-template)
3. [NestJS Controller Test Template](#nestjs-controller-test-template)
4. [React Component Test Template](#react-component-test-template)
5. [React Hook Test Template](#react-hook-test-template)
6. [Zustand Store Test Template](#zustand-store-test-template)
7. [Zod Schema Test Template](#zod-schema-test-template)
8. [Mock Patterns](#mock-patterns)
9. [Test Naming Convention](#test-naming-convention)
10. [Common Pitfalls](#common-pitfalls)

---

## Vitest Configuration

### Backend (NestJS)

```typescript
// vitest.config.ts (backend root)
import { defineConfig } from 'vitest/config';
import swc from 'unplugin-swc';
import { resolve } from 'path';

export default defineConfig({
  plugins: [swc.vite()], // Required for NestJS decorators
  test: {
    globals: true,
    root: resolve(__dirname),
    include: ['src/**/*.spec.ts'],
    exclude: [
      'src/**/*.e2e-spec.ts',      // Exclude E2E
      'src/**/*.isolation.spec.ts', // Separate CI step
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      include: ['src/modules/**/*.ts'],
      exclude: [
        'src/modules/**/*.module.ts',
        'src/modules/**/*.dto.ts',
        'src/modules/**/index.ts',
        'src/**/*.spec.ts',
      ],
      thresholds: {
        branches: 70,
        functions: 70,
        lines: 80,
        statements: 80,
      },
    },
    setupFiles: ['./test/setup.ts'],
    pool: 'forks',
    poolOptions: {
      forks: { maxForks: 4 },
    },
  },
});
```

### Frontend (Next.js)

```typescript
// vitest.config.ts (frontend root)
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**/*'],
    setupFiles: ['./test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      include: ['src/features/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}'],
      exclude: [
        'src/**/index.ts',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.stories.{ts,tsx}',
      ],
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

### Test Setup Files

```typescript
// test/setup.ts (backend)
import { vi } from 'vitest';

// Mock logger globally to suppress noise
vi.mock('./src/common/logger', () => ({
  Logger: {
    log: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    debug: vi.fn(),
  },
}));

// Reset all mocks between tests
afterEach(() => {
  vi.restoreAllMocks();
});
```

```typescript
// test/setup.ts (frontend)
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { vi } from 'vitest';

// Cleanup DOM after each test
afterEach(() => {
  cleanup();
});

// Mock next/navigation globally
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => '/en/recipients',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ locale: 'en' }),
}));

// Mock next-intl
vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => 'en',
}));
```

---

## NestJS Service Test Template

Services contain business logic. Mock repositories, external services, and guards.

### Basic Service Test

```typescript
import { Test, TestingModule } from '@nestjs/testing';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { CampaignsService } from '../campaigns.service';
import { CampaignsRepository } from '../campaigns.repository';
import { RecipientsRepository } from '../../recipients/recipients.repository';
import { AuditService } from '../../audit/audit.service';
import { PlanManager } from '../../billing/plan.manager';
import { Queue } from 'bullmq';
import { ForbiddenException, NotFoundException } from '@nestjs/common';

describe('CampaignsService', () => {
  let service: CampaignsService;
  let campaignRepo: CampaignsRepository;
  let recipientRepo: RecipientsRepository;
  let queue: Queue;

  const tenantContext = {
    domainId: 'domain-1',
    workspaceId: 'ws-1',
    companyId: 'company-1',
    subscriptionTier: 'pro' as const,
    subscriptionStatus: 'active' as const,
    seatsLimit: 10,
    recipientLimit: 50_000,
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        CampaignsService,
        {
          provide: CampaignsRepository,
          useValue: {
            create: vi.fn(),
            findById: vi.fn(),
            findMany: vi.fn(),
            update: vi.fn(),
            softDelete: vi.fn(),
          },
        },
        {
          provide: RecipientsRepository,
          useValue: {
            countByDomain: vi.fn(),
            findByFilter: vi.fn(),
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
            }),
          },
        },
        {
          provide: 'BullQueue_campaigns',
          useValue: { add: vi.fn() },
        },
      ],
    }).compile();

    service = module.get(CampaignsService);
    campaignRepo = module.get(CampaignsRepository);
    recipientRepo = module.get(RecipientsRepository);
    queue = module.get('BullQueue_campaigns');
  });

  describe('create', () => {
    const createDto = {
      name: 'Q1 Phishing Test',
      scenarioId: 'sc-1',
      targetFilter: { department: 'Engineering' },
    };

    it('should create campaign with correct tenant IDs', async () => {
      vi.mocked(campaignRepo.create).mockResolvedValue({
        id: 'camp-1',
        ...createDto,
        domainId: tenantContext.domainId,
        workspaceId: tenantContext.workspaceId,
        companyId: tenantContext.companyId,
        status: 'draft',
      });

      const result = await service.create(tenantContext, createDto);

      expect(campaignRepo.create).toHaveBeenCalledWith(
        expect.objectContaining({
          domainId: 'domain-1',
          workspaceId: 'ws-1',
          companyId: 'company-1',
          status: 'draft',
        }),
      );
      expect(result.id).toBe('camp-1');
    });

    it('should audit log creation', async () => {
      vi.mocked(campaignRepo.create).mockResolvedValue({ id: 'camp-1', ...createDto });
      const auditService = module.get(AuditService);

      await service.create(tenantContext, createDto);

      expect(auditService.log).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'campaign.created',
          workspaceId: 'ws-1',
        }),
      );
    });
  });

  describe('launch', () => {
    it('should enqueue job when target count exceeds 1000', async () => {
      vi.mocked(campaignRepo.findById).mockResolvedValue({
        id: 'camp-1',
        domainId: 'domain-1',
        workspaceId: 'ws-1',
        status: 'draft',
        targetFilter: {},
      });
      vi.mocked(recipientRepo.countByDomain).mockResolvedValue(5000);

      const result = await service.launch(tenantContext, 'camp-1');

      expect(queue.add).toHaveBeenCalledWith(
        'launch-campaign',
        expect.objectContaining({ campaignId: 'camp-1' }),
      );
      expect(result.status).toBe('queued');
    });

    it('should throw NotFoundException for non-existent campaign', async () => {
      vi.mocked(campaignRepo.findById).mockResolvedValue(null);

      await expect(
        service.launch(tenantContext, 'non-existent'),
      ).rejects.toThrow(NotFoundException);
    });

    it('should throw ForbiddenException if campaign belongs to different workspace', async () => {
      vi.mocked(campaignRepo.findById).mockResolvedValue({
        id: 'camp-1',
        domainId: 'domain-1',
        workspaceId: 'ws-OTHER', // Different workspace
        status: 'draft',
      });

      await expect(
        service.launch(tenantContext, 'camp-1'),
      ).rejects.toThrow(ForbiddenException);
    });
  });

  describe('delete', () => {
    it('should soft-delete campaign and log audit', async () => {
      vi.mocked(campaignRepo.findById).mockResolvedValue({
        id: 'camp-1',
        workspaceId: 'ws-1',
        status: 'draft',
      });
      vi.mocked(campaignRepo.softDelete).mockResolvedValue({ affected: 1 });

      await service.delete(tenantContext, 'camp-1');

      expect(campaignRepo.softDelete).toHaveBeenCalledWith('camp-1');
    });

    it('should NOT delete campaign with status "active"', async () => {
      vi.mocked(campaignRepo.findById).mockResolvedValue({
        id: 'camp-1',
        workspaceId: 'ws-1',
        status: 'active', // Cannot delete active campaigns
      });

      await expect(
        service.delete(tenantContext, 'camp-1'),
      ).rejects.toThrow('Cannot delete active campaign');
    });
  });
});
```

### Testing Additive Limit Check

```typescript
describe('additive limit check', () => {
  it('should allow import when existing + incoming <= limit', async () => {
    vi.mocked(recipientRepo.countByCompany).mockResolvedValue(49_000);

    // 49000 existing + 500 incoming = 49500 <= 50000 limit
    await expect(
      service.validateImportLimit(tenantContext, 500),
    ).resolves.not.toThrow();
  });

  it('should reject import when existing + incoming > limit', async () => {
    vi.mocked(recipientRepo.countByCompany).mockResolvedValue(49_800);

    // 49800 existing + 500 incoming = 50300 > 50000 limit
    await expect(
      service.validateImportLimit(tenantContext, 500),
    ).rejects.toThrow('Would exceed recipient limit (49800 + 500 > 50000)');
  });

  it('should use company-level count, not workspace-level', async () => {
    await service.validateImportLimit(tenantContext, 100);

    // Must count at company level for billing enforcement
    expect(recipientRepo.countByCompany).toHaveBeenCalledWith('company-1');
    expect(recipientRepo.countByCompany).not.toHaveBeenCalledWith('ws-1');
  });
});
```

---

## NestJS Controller Test Template

Controllers are thin — test them at integration level with supertest. Unit tests for controllers
are only necessary when testing DTO transformation or response shaping logic.

```typescript
import { Test } from '@nestjs/testing';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { RecipientsController } from '../recipients.controller';
import { RecipientsService } from '../recipients.service';

describe('RecipientsController (Unit)', () => {
  let controller: RecipientsController;
  let service: RecipientsService;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      controllers: [RecipientsController],
      providers: [
        {
          provide: RecipientsService,
          useValue: {
            findMany: vi.fn(),
            create: vi.fn(),
            update: vi.fn(),
            delete: vi.fn(),
          },
        },
      ],
    }).compile();

    controller = module.get(RecipientsController);
    service = module.get(RecipientsService);
  });

  describe('findAll', () => {
    it('should call service.findMany with tenantContext and filter', async () => {
      const tenantContext = { domainId: 'd-1', workspaceId: 'ws-1', companyId: 'c-1' };
      const filter = { status: 'active', page: 1, limit: 50 };

      vi.mocked(service.findMany).mockResolvedValue({
        data: [],
        meta: { total: 0, page: 1, pageSize: 50, hasMore: false },
      });

      const result = await controller.findAll(tenantContext, filter);

      expect(service.findMany).toHaveBeenCalledWith(tenantContext, filter);
      expect(result.meta).toBeDefined();
    });
  });

  describe('create', () => {
    it('should pass tenantContext and DTO to service', async () => {
      const tenantContext = { domainId: 'd-1', workspaceId: 'ws-1', companyId: 'c-1' };
      const dto = { email: 'test@test.com', firstName: 'Test', lastName: 'User' };

      vi.mocked(service.create).mockResolvedValue({ id: 'r-1', ...dto });

      const result = await controller.create(tenantContext, dto);

      expect(service.create).toHaveBeenCalledWith(tenantContext, dto);
      expect(result.id).toBe('r-1');
    });
  });
});
```

---

## React Component Test Template

### Basic Component Test

```typescript
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RecipientDetail } from '../recipient-detail';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const mockRecipient = {
  id: 'r-1',
  email: 'rajesh@tatasteel.com',
  firstName: 'Rajesh',
  lastName: 'Kumar',
  status: 'active' as const,
  department: 'Engineering',
  tags: ['vip', 'engineering'],
  customFields: { location: 'Mumbai' },
  createdAt: '2024-01-15T10:00:00Z',
  updatedAt: '2024-03-10T14:30:00Z',
};

describe('RecipientDetail', () => {
  it('should display recipient name and email', () => {
    render(
      <RecipientDetail recipient={mockRecipient} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('Rajesh Kumar')).toBeInTheDocument();
    expect(screen.getByText('rajesh@tatasteel.com')).toBeInTheDocument();
  });

  it('should display status badge with correct variant', () => {
    render(
      <RecipientDetail recipient={mockRecipient} />,
      { wrapper: createWrapper() },
    );

    const badge = screen.getByText('active');
    expect(badge).toHaveClass(/green|success/);
  });

  it('should display tags as chips', () => {
    render(
      <RecipientDetail recipient={mockRecipient} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('vip')).toBeInTheDocument();
    expect(screen.getByText('engineering')).toBeInTheDocument();
  });

  it('should display custom fields', () => {
    render(
      <RecipientDetail recipient={mockRecipient} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('Mumbai')).toBeInTheDocument();
  });

  it('should call onEdit when edit button clicked', async () => {
    const handleEdit = vi.fn();
    const user = userEvent.setup();

    render(
      <RecipientDetail recipient={mockRecipient} onEdit={handleEdit} />,
      { wrapper: createWrapper() },
    );

    await user.click(screen.getByRole('button', { name: /edit/i }));
    expect(handleEdit).toHaveBeenCalledWith('r-1');
  });

  it('should show confirmation dialog on delete', async () => {
    const user = userEvent.setup();

    render(
      <RecipientDetail recipient={mockRecipient} onDelete={vi.fn()} />,
      { wrapper: createWrapper() },
    );

    await user.click(screen.getByRole('button', { name: /delete/i }));

    // Confirmation dialog should appear
    expect(screen.getByText(/are you sure/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument();
  });
});
```

### Testing Data Table Component

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RecipientsDataTable } from '../recipients-data-table';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const mockData = [
  { id: '1', email: 'alice@tatasteel.com', firstName: 'Alice', lastName: 'K', status: 'active', department: 'Engineering' },
  { id: '2', email: 'bob@tatasteel.com', firstName: 'Bob', lastName: 'S', status: 'bounced', department: 'Marketing' },
  { id: '3', email: 'carol@tatasteel.com', firstName: 'Carol', lastName: 'P', status: 'active', department: 'Engineering' },
];

describe('RecipientsDataTable', () => {
  it('should render all rows', () => {
    render(
      <RecipientsDataTable data={mockData} isLoading={false} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('alice@tatasteel.com')).toBeInTheDocument();
    expect(screen.getByText('bob@tatasteel.com')).toBeInTheDocument();
    expect(screen.getByText('carol@tatasteel.com')).toBeInTheDocument();
  });

  it('should show loading skeleton when isLoading is true', () => {
    render(
      <RecipientsDataTable data={[]} isLoading={true} />,
      { wrapper: createWrapper() },
    );

    // Skeleton rows should be visible
    expect(screen.getByTestId('table-skeleton')).toBeInTheDocument();
  });

  it('should show empty state when data is empty and not loading', () => {
    render(
      <RecipientsDataTable data={[]} isLoading={false} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText(/no recipients/i)).toBeInTheDocument();
  });

  it('should filter rows by search input', async () => {
    const user = userEvent.setup();
    render(
      <RecipientsDataTable data={mockData} isLoading={false} />,
      { wrapper: createWrapper() },
    );

    const searchInput = screen.getByPlaceholderText(/search/i);
    await user.type(searchInput, 'alice');

    expect(screen.getByText('alice@tatasteel.com')).toBeInTheDocument();
    expect(screen.queryByText('bob@tatasteel.com')).not.toBeInTheDocument();
  });

  it('should enable bulk actions when rows are selected', async () => {
    const user = userEvent.setup();
    render(
      <RecipientsDataTable data={mockData} isLoading={false} />,
      { wrapper: createWrapper() },
    );

    // Select first row checkbox
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[1]); // First data row (index 0 is "select all")

    expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete/i })).toBeEnabled();
  });
});
```

### Testing Progressive Complexity

```typescript
describe('Progressive Complexity', () => {
  it('should hide workspace selector for UC1 (single workspace)', () => {
    render(
      <Navigation workspaces={[{ id: 'ws-1', name: 'Zerodha' }]} />,
      { wrapper: createWrapper() },
    );

    expect(screen.queryByTestId('workspace-selector')).not.toBeInTheDocument();
  });

  it('should show workspace selector for UC3 (multiple workspaces)', () => {
    render(
      <Navigation workspaces={[
        { id: 'ws-1', name: 'Tata Steel' },
        { id: 'ws-2', name: 'Tata Motors' },
      ]} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByTestId('workspace-selector')).toBeInTheDocument();
  });

  it('should hide domain tabs when workspace has single domain', () => {
    render(
      <RecipientsPage domains={[{ id: 'd-1', name: 'zerodha.com' }]} />,
      { wrapper: createWrapper() },
    );

    expect(screen.queryByTestId('domain-tabs')).not.toBeInTheDocument();
  });

  it('should show domain tabs when workspace has multiple domains', () => {
    render(
      <RecipientsPage domains={[
        { id: 'd-1', name: 'jio.com' },
        { id: 'd-2', name: 'jiosaavn.com' },
      ]} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByTestId('domain-tabs')).toBeInTheDocument();
    expect(screen.getByText('jio.com')).toBeInTheDocument();
    expect(screen.getByText('jiosaavn.com')).toBeInTheDocument();
  });

  it('should hide Person column for UC1', () => {
    render(
      <RecipientsDataTable
        data={mockData}
        isLoading={false}
        showPersonColumn={false}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.queryByText(/person|identities/i)).not.toBeInTheDocument();
  });
});
```

---

## React Hook Test Template

### Custom Query Hook

```typescript
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useRecipient, useRecipients } from '../hooks/use-recipients';
import { recipientsApi } from '../lib/api';

vi.mock('../lib/api');

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useRecipients', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should return loading state initially', () => {
    vi.mocked(recipientsApi.list).mockReturnValue(new Promise(() => {})); // Never resolves

    const { result } = renderHook(() => useRecipients(), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });

  it('should return data on success', async () => {
    const mockData = [
      { id: '1', email: 'a@test.com', firstName: 'Alice', lastName: 'K' },
    ];
    vi.mocked(recipientsApi.list).mockResolvedValue(mockData);

    const { result } = renderHook(() => useRecipients(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it('should return error state on failure', async () => {
    vi.mocked(recipientsApi.list).mockRejectedValue(new Error('Server error'));

    const { result } = renderHook(() => useRecipients(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('Server error');
  });

  it('should refetch when filter changes', async () => {
    vi.mocked(recipientsApi.list).mockResolvedValue([]);

    const { result, rerender } = renderHook(
      ({ filter }) => useRecipients(filter),
      {
        wrapper: createWrapper(),
        initialProps: { filter: { status: ['active'] } },
      },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(recipientsApi.list).toHaveBeenCalledWith({ status: ['active'] });

    rerender({ filter: { status: ['bounced'] } });

    await waitFor(() =>
      expect(recipientsApi.list).toHaveBeenCalledWith({ status: ['bounced'] }),
    );
  });
});

describe('useRecipient (single)', () => {
  it('should not fetch when id is empty', () => {
    vi.mocked(recipientsApi.getById).mockResolvedValue({} as any);

    renderHook(() => useRecipient(''), { wrapper: createWrapper() });

    expect(recipientsApi.getById).not.toHaveBeenCalled();
  });

  it('should fetch when id is provided', async () => {
    const mockRecipient = { id: 'r-1', email: 'a@test.com' };
    vi.mocked(recipientsApi.getById).mockResolvedValue(mockRecipient);

    const { result } = renderHook(() => useRecipient('r-1'), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockRecipient);
  });
});
```

### Custom Mutation Hook

```typescript
describe('useDeleteRecipient', () => {
  it('should call API with correct id', async () => {
    vi.mocked(recipientsApi.delete).mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteRecipient(), { wrapper: createWrapper() });

    result.current.mutate('r-1');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(recipientsApi.delete).toHaveBeenCalledWith('r-1');
  });

  it('should expose error on failure', async () => {
    vi.mocked(recipientsApi.delete).mockRejectedValue(new Error('Not found'));

    const { result } = renderHook(() => useDeleteRecipient(), { wrapper: createWrapper() });

    result.current.mutate('non-existent');

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('Not found');
  });
});

describe('useBulkDeleteRecipients', () => {
  it('should send array of IDs to API', async () => {
    vi.mocked(recipientsApi.bulkDelete).mockResolvedValue({ deleted: 3 });

    const { result } = renderHook(() => useBulkDeleteRecipients(), { wrapper: createWrapper() });

    result.current.mutate(['r-1', 'r-2', 'r-3']);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(recipientsApi.bulkDelete).toHaveBeenCalledWith(['r-1', 'r-2', 'r-3']);
    expect(result.current.data).toEqual({ deleted: 3 });
  });
});
```

---

## Zustand Store Test Template

### Basic Store Test

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useWorkspaceStore } from '../stores/workspace-store';

describe('WorkspaceStore', () => {
  beforeEach(() => {
    // CRITICAL: Reset state between tests. Zustand stores are singletons.
    useWorkspaceStore.setState(
      {
        activeWorkspaceId: null,
        activeCompanyId: null,
        workspaces: [],
      },
      true, // Replace entire state
    );
  });

  it('should initialize with null workspace', () => {
    const state = useWorkspaceStore.getState();
    expect(state.activeWorkspaceId).toBeNull();
  });

  it('should set active workspace', () => {
    act(() => {
      useWorkspaceStore.getState().setActiveWorkspace('ws-1');
    });
    expect(useWorkspaceStore.getState().activeWorkspaceId).toBe('ws-1');
  });

  it('should load workspaces for company', () => {
    act(() => {
      useWorkspaceStore.getState().loadWorkspaces([
        { id: 'ws-1', name: 'Tata Steel', companyId: 'c-1' },
        { id: 'ws-2', name: 'Tata Motors', companyId: 'c-1' },
      ]);
    });

    const state = useWorkspaceStore.getState();
    expect(state.workspaces).toHaveLength(2);
  });
});
```

### Testing Store with Persist Middleware

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useSidebarStore } from '../stores/sidebar-store';

// Mock localStorage for persist middleware tests
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

describe('SidebarStore (persisted)', () => {
  beforeEach(() => {
    localStorageMock.clear();
    useSidebarStore.setState({ isCollapsed: false, width: 280 }, true);
  });

  it('should toggle collapse state', () => {
    act(() => {
      useSidebarStore.getState().toggleCollapse();
    });
    expect(useSidebarStore.getState().isCollapsed).toBe(true);
  });

  it('should persist width to localStorage', () => {
    act(() => {
      useSidebarStore.getState().setWidth(320);
    });
    expect(useSidebarStore.getState().width).toBe(320);
    // Persist middleware writes asynchronously — verify the state is correct
  });
});
```

---

## Zod Schema Test Template

### Entity Schema Tests

```typescript
import { describe, it, expect } from 'vitest';
import {
  CreateRecipientSchema,
  UpdateRecipientSchema,
  RecipientFilterSchema,
  BulkDeleteSchema,
} from '../types';

describe('CreateRecipientSchema', () => {
  const validInput = {
    email: 'rajesh@tatasteel.com',
    firstName: 'Rajesh',
    lastName: 'Kumar',
    status: 'active',
    department: 'Engineering',
  };

  it('should accept valid complete input', () => {
    const result = CreateRecipientSchema.safeParse(validInput);
    expect(result.success).toBe(true);
  });

  it('should accept minimal required fields', () => {
    const result = CreateRecipientSchema.safeParse({
      email: 'test@test.com',
      firstName: 'Test',
      lastName: 'User',
    });
    expect(result.success).toBe(true);
  });

  it('should apply default status "active"', () => {
    const result = CreateRecipientSchema.parse({
      email: 'test@test.com',
      firstName: 'Test',
      lastName: 'User',
    });
    expect(result.status).toBe('active');
  });

  it('should reject invalid email format', () => {
    const result = CreateRecipientSchema.safeParse({
      ...validInput,
      email: 'not-an-email',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain('email');
    }
  });

  it('should reject empty email', () => {
    const result = CreateRecipientSchema.safeParse({
      ...validInput,
      email: '',
    });
    expect(result.success).toBe(false);
  });

  it('should reject empty firstName', () => {
    const result = CreateRecipientSchema.safeParse({
      ...validInput,
      firstName: '',
    });
    expect(result.success).toBe(false);
  });

  it('should reject invalid status enum value', () => {
    const result = CreateRecipientSchema.safeParse({
      ...validInput,
      status: 'unknown',
    });
    expect(result.success).toBe(false);
  });

  it('should strip unknown fields', () => {
    const result = CreateRecipientSchema.parse({
      ...validInput,
      malicious: 'payload',
    });
    expect((result as any).malicious).toBeUndefined();
  });
});

describe('RecipientFilterSchema', () => {
  it('should accept empty object (all defaults)', () => {
    const result = RecipientFilterSchema.safeParse({});
    expect(result.success).toBe(true);
  });

  it('should coerce string page/limit to numbers', () => {
    const result = RecipientFilterSchema.parse({
      page: '2',
      limit: '25',
    });
    expect(result.page).toBe(2);
    expect(result.limit).toBe(25);
  });

  it('should apply default page=1 and limit=50', () => {
    const result = RecipientFilterSchema.parse({});
    expect(result.page).toBe(1);
    expect(result.limit).toBe(50);
  });

  it('should reject negative page', () => {
    const result = RecipientFilterSchema.safeParse({ page: -1 });
    expect(result.success).toBe(false);
  });

  it('should cap limit at maximum (e.g., 200)', () => {
    const result = RecipientFilterSchema.parse({ limit: 1000 });
    expect(result.limit).toBeLessThanOrEqual(200);
  });

  it('should accept status as string array', () => {
    const result = RecipientFilterSchema.parse({
      status: ['active', 'bounced'],
    });
    expect(result.status).toEqual(['active', 'bounced']);
  });
});

describe('BulkDeleteSchema', () => {
  it('should accept non-empty array of UUIDs', () => {
    const result = BulkDeleteSchema.safeParse({
      ids: ['550e8400-e29b-41d4-a716-446655440000'],
    });
    expect(result.success).toBe(true);
  });

  it('should reject empty array', () => {
    const result = BulkDeleteSchema.safeParse({ ids: [] });
    expect(result.success).toBe(false);
  });

  it('should reject non-UUID strings', () => {
    const result = BulkDeleteSchema.safeParse({ ids: ['not-a-uuid'] });
    expect(result.success).toBe(false);
  });
});
```

---

## Mock Patterns

### When to Mock (Unit Tests)

| Dependency | Mock Strategy | Why |
|-----------|--------------|-----|
| Repository | `vi.fn()` per method | Isolate business logic from DB |
| Redis | `{ get: vi.fn(), set: vi.fn() }` | No real Redis in unit tests |
| BullMQ Queue | `{ add: vi.fn() }` | Verify job enqueued with correct payload |
| AuditService | `{ log: vi.fn() }` | Verify audit logged without side effects |
| External APIs | `vi.mock('axios')` | No network calls in unit tests |
| `Date.now()` | `vi.setSystemTime()` | Deterministic timestamps |
| `randomUUID()` | `vi.fn().mockReturnValue('fixed-uuid')` | Deterministic IDs in snapshots |

### When NOT to Mock

| Dependency | Why Keep Real |
|-----------|--------------|
| Zod schemas | They ARE the logic under test |
| Utility functions | Pure functions with no side effects |
| Type guards | Simple boolean logic |
| TanStack Query hooks | Wrap in QueryClientProvider instead |
| Zustand stores | They are synchronous state containers |

### Mock Template: Repository

```typescript
const mockRepository = {
  findMany: vi.fn(),
  findById: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  softDelete: vi.fn(),
  countByDomain: vi.fn(),
  countByCompany: vi.fn(),
  countByFilter: vi.fn(),
  batchUpdate: vi.fn(),
};
```

### Mock Template: API Service (Frontend)

```typescript
vi.mock('../lib/api', () => ({
  recipientsApi: {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    bulkDelete: vi.fn(),
    import: vi.fn(),
  },
}));
```

### Mock Template: Next.js Router

```typescript
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/en/recipients',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ locale: 'en', workspaceId: 'ws-1' }),
}));
```

---

## Test Naming Convention

### Pattern

```
describe('ClassOrComponentName')
  describe('methodOrFeature')
    it('should [expected behavior] when [condition/input]')
```

### Good Names

```typescript
it('should create recipient when under limit')
it('should throw PaymentRequiredException when recipient limit exceeded')
it('should return empty array for domain with no data')
it('should log audit event on successful creation')
it('should disable submit button while submitting')
it('should show validation error for invalid email')
it('should invalidate list queries after successful delete')
it('should hide workspace selector for UC1 users')
```

### Bad Names (Avoid)

```typescript
it('works')                              // Too vague
it('test create')                        // Not a sentence
it('should handle error')               // Which error? What handling?
it('recipient creation test')           // Describe format, not noun
it('creates recipient and logs audit')  // Two behaviors = two tests
```

---

## Common Pitfalls

### 1. Not Resetting Zustand Stores Between Tests

```typescript
// BAD: State leaks between tests
describe('WorkspaceStore', () => {
  it('test A sets workspace', () => {
    useWorkspaceStore.getState().setActiveWorkspace('ws-1');
  });
  it('test B sees ws-1 from test A', () => {
    // FAILS intermittently — depends on test order
  });
});

// GOOD: Reset in beforeEach
beforeEach(() => {
  useWorkspaceStore.setState(initialState, true);
});
```

### 2. Not Awaiting waitFor for Async Hooks

```typescript
// BAD: Assert before data loads
const { result } = renderHook(() => useRecipients());
expect(result.current.data).toHaveLength(1); // Fails — data is undefined

// GOOD: Wait for success
await waitFor(() => expect(result.current.isSuccess).toBe(true));
expect(result.current.data).toHaveLength(1);
```

### 3. Mocking Too Deep or Too Shallow

```typescript
// BAD: Mocking internal implementation details
vi.mock('drizzle-orm', () => ({ eq: vi.fn() }));

// BAD: Not mocking at all (hits real DB in unit test)
const repo = new RecipientsRepository(realDb);

// GOOD: Mock at the repository boundary
const mockRepo = { findMany: vi.fn().mockResolvedValue([...]) };
```

### 4. Using act() Unnecessarily

```typescript
// BAD: Wrapping everything in act
act(() => { render(<Component />) }); // render already wraps in act

// GOOD: Only use act for Zustand state updates outside React
act(() => { useStore.getState().someAction(); });
```

### 5. Not Testing Error States

```typescript
// BAD: Only testing happy path
it('should fetch recipients', async () => { /* ... */ });

// GOOD: Testing both paths
it('should return data on success', async () => { /* ... */ });
it('should return error state on API failure', async () => { /* ... */ });
it('should show error message in UI on failure', async () => { /* ... */ });
```

### 6. Asserting on Implementation Instead of Behavior

```typescript
// BAD: Testing implementation
expect(component.state.isLoading).toBe(true);

// GOOD: Testing behavior (what the user sees)
expect(screen.getByTestId('loading-skeleton')).toBeInTheDocument();
```
