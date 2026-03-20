---
name: frontend-architect-skill
description: Unified frontend architect for Next.js 16 + React 19 + TypeScript 5 + Tailwind 4 + Zustand 5 + TanStack Query 5 + TanStack Table + Better Auth. Transforms feature requirements into production-grade, multi-tenant, component-driven frontend implementations with mock/real API adapter pattern. Trigger when building any frontend feature, page, component, form, wizard, table, dashboard, or UI module. Also for state management decisions, API integration, data table config, form validation, wizard patterns, mock data setup, or any React/Next.js architecture question.
---

# Frontend Architect Skill

Unified enterprise frontend architecture for **Next.js 16 + React 19 + TypeScript 5 + Tailwind 4 + Zustand 5 + TanStack Query 5 + TanStack Table 8 + Better Auth**.

Transforms feature requirements into production-grade, multi-tenant, component-driven frontend implementations.

## Reference Files

| File | What It Covers |
|------|---------------|
| `SKILL.md` | This file — 7-phase flow, patterns, checklists |
| `folder-structure.md` | Complete project layout with every directory |
| `library-decisions.md` | 30+ locked library decisions + when NOT to use alternatives |
| `table-reference.md` | UnifiedDataTable API — props, columns, filters, persistence |
| `wizard-reference.md` | Multi-step wizard architecture from CSV import reference |
| `migration-skill.md` | **How to migrate any legacy Next.js project to the correct architecture** — 7-phase plan with diagnosis checklist, templates, and anti-pattern fixes |

## Current Platform Status

When migrating an existing Next.js project to this architecture, key production-grade assets should be preserved (not rewritten):

- **UnifiedDataTable** — if a headless TanStack Table wrapper exists with persistence, DnD, and filters, keep it and move to `features/{name}/components/ui/`
- **Import Wizards** — if multi-step import flows exist with auto-mapping and duplicate detection, preserve them in `features/{name}/components/import/`
- **JSON data layer** — if `lib/data/*.ts` files provide a file-based backend, keep for demo mode and wrap with `fetchApi()` adapter
- **shadcn/ui components** — always keep in `components/ui/`, never modify

See `migration-skill.md` for the generic 7-phase migration plan.

## Immutable Stack (Locked Decisions)

| Concern | Technology | Why |
|---------|-----------|-----|
| Framework | Next.js 16 (App Router + Turbopack) | SSR, routing, middleware, API routes |
| UI Library | React 19 | Concurrent rendering, server components |
| Language | TypeScript 5 (strict) | Type safety, IDE support |
| Styling | Tailwind CSS 4 (OKLCH colors) | Utility-first, design tokens |
| Components | shadcn/ui (61+ components) | Radix primitives, customizable |
| Client State | Zustand 5 | Lightweight, middleware, persist |
| Server State | TanStack Query 5 | Caching, mutations, devtools |
| Data Tables | TanStack Table 8 + @dnd-kit | Headless, sortable, filterable |
| Forms | react-hook-form + Zod | Validation, performance |
| Auth | Better Auth | Session, OAuth, middleware |
| i18n | next-intl (5 locales + RTL) | Static rendering, type-safe |
| Icons | lucide-react | Tree-shakeable, consistent |
| Toasts | sonner | Beautiful, accessible |
| DnD | @dnd-kit/core + sortable | Column reorder, list sort |

## Seven-Phase Flow (Apply to Every Feature)

### Phase 0: Types & Contracts

Before touching any component, define the data shape:

```
src/features/{feature}/types.ts
```

```typescript
// Entity types
export interface Recipient {
  id: string
  email: string
  firstName: string
  lastName: string
  status: 'active' | 'inactive' | 'bounced'
  department?: string
  tags: string[]
  customFields: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

// Filter types
export interface RecipientFilter {
  status?: string[]
  department?: string[]
  search?: string
  page?: number
  limit?: number
}

// Form types (Zod schemas)
export const CreateRecipientSchema = z.object({
  email: z.string().email(),
  firstName: z.string().min(1),
  lastName: z.string().min(1),
  status: z.enum(['active', 'inactive']).default('active'),
})
export type CreateRecipientInput = z.infer<typeof CreateRecipientSchema>
```

**Rules:**
- Types FIRST, components SECOND
- Zod schemas for ALL form inputs
- Export types from `features/{name}/index.ts`
- Shared types go in `src/types/index.ts`

### Phase 1: Mock Data & API Service

Build the data layer before any UI:

```
src/features/{feature}/lib/api.ts          # API service
src/lib/api/mock/{feature}.ts              # Mock data + handler
```

**API Service Pattern:**
```typescript
// src/features/recipients/lib/api.ts
import { fetchApi, buildQueryString } from '@/lib/api/client'
import type { Recipient, RecipientFilter, CreateRecipientInput } from '../types'

export const recipientsApi = {
  async list(filter?: RecipientFilter): Promise<Recipient[]> {
    const query = filter ? buildQueryString(filter) : ''
    return fetchApi<Recipient[]>(`/api/recipients${query}`)
  },

  async getById(id: string): Promise<Recipient> {
    return fetchApi<Recipient>(`/api/recipients/${id}`)
  },

  async create(payload: CreateRecipientInput): Promise<Recipient> {
    return fetchApi<Recipient>('/api/recipients', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async update(id: string, payload: Partial<CreateRecipientInput>): Promise<Recipient> {
    return fetchApi<Recipient>(`/api/recipients/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },

  async delete(id: string): Promise<void> {
    return fetchApi<void>(`/api/recipients/${id}`, { method: 'DELETE' })
  },

  async bulkDelete(ids: string[]): Promise<{ deleted: number }> {
    return fetchApi('/api/recipients/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    })
  },

  async import(recipients: CreateRecipientInput[], options?: { duplicateHandling: string }): Promise<{ imported: number; skipped: number }> {
    return fetchApi('/api/recipients/import', {
      method: 'POST',
      body: JSON.stringify({ recipients, ...options }),
    })
  },
}
```

**Adapter Pattern (Mock/Real switching):**
```typescript
// fetchApi auto-detects mode from env/localStorage
// NEXT_PUBLIC_API_MODE=mock  → routes to handleMockRequest()
// NEXT_PUBLIC_API_MODE=real  → routes to fetch() with auth headers

// Mock handler: src/lib/api/mock/handler.ts
// Add your feature's routes to the router
```

**Rules:**
- API service is a plain object with async methods (NOT a class)
- Every method returns typed promises
- Mock data must be realistic (use real-world Indian names, departments, etc.)
- Mock handler simulates 300ms network delay
- ALWAYS build mock first, connect real API later

### Phase 2: React Query Hooks

Wrap API service with caching and mutations:

```
src/features/{feature}/hooks/use-{feature}.ts
```

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { recipientsApi } from '../lib/api'
import type { RecipientFilter } from '../types'

// Query key hierarchy (MANDATORY pattern)
export const recipientKeys = {
  all: ['recipients'] as const,
  lists: () => [...recipientKeys.all, 'list'] as const,
  list: (filter?: RecipientFilter) => [...recipientKeys.lists(), filter] as const,
  details: () => [...recipientKeys.all, 'detail'] as const,
  detail: (id: string) => [...recipientKeys.details(), id] as const,
  metrics: () => [...recipientKeys.all, 'metrics'] as const,
}

// Query hooks
export function useRecipients(filter?: RecipientFilter) {
  return useQuery({
    queryKey: recipientKeys.list(filter),
    queryFn: () => recipientsApi.list(filter),
  })
}

export function useRecipient(id: string) {
  return useQuery({
    queryKey: recipientKeys.detail(id),
    queryFn: () => recipientsApi.getById(id),
    enabled: !!id,
  })
}

// Mutation hooks
export function useCreateRecipient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: recipientsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: recipientKeys.lists() })
      queryClient.invalidateQueries({ queryKey: recipientKeys.metrics() })
    },
  })
}

export function useUpdateRecipient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<CreateRecipientInput> }) =>
      recipientsApi.update(id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(recipientKeys.detail(updated.id), updated)
      queryClient.invalidateQueries({ queryKey: recipientKeys.lists() })
    },
  })
}

export function useDeleteRecipient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: recipientsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: recipientKeys.lists() })
      queryClient.invalidateQueries({ queryKey: recipientKeys.metrics() })
    },
  })
}
```

**Rules:**
- Query keys are ALWAYS hierarchical objects (not magic strings)
- `onSuccess` ALWAYS invalidates relevant queries
- `enabled` flag for conditional fetching
- Export from `features/{name}/hooks/index.ts`

### Phase 3: Components

Build UI components using the established patterns:

```
src/features/{feature}/components/
  ├── {feature}-data-table.tsx      # UnifiedDataTable wrapper
  ├── {feature}-columns.tsx         # Column definitions
  ├── {feature}-form.tsx            # Create/edit form
  ├── {feature}-detail.tsx          # Detail sidepanel/page
  ├── {feature}-filters.tsx         # Filter components
  └── index.ts                      # Exports
```

**Data Table Pattern (MANDATORY for any list view):**
```typescript
// Use UnifiedDataTable — never build a custom table from scratch
<UnifiedDataTable<Recipient, unknown>
  columns={columns}
  data={data}
  localStoragePrefix="recipients-table"
  enableRowSelection
  enableSearch
  searchPlaceholder="Search recipients..."
  columnDefaults={{
    pinned: { left: ['select'], right: ['actions'] },
    visibility: { /* hidden columns */ },
  }}
  filters={[
    { id: 'status', column: 'status', title: 'Status', options: statusOptions, defaultVisible: true },
    { id: 'department', column: 'department', title: 'Department', options: deptOptions },
  ]}
  bulkActions={[
    { id: 'delete', label: 'Delete', variant: 'destructive', onExecute: handleBulkDelete, confirm: { ... } },
  ]}
  tableMeta={{ onUpdateField, onViewDetails }}
/>
```

**Column Definition Pattern:**
```typescript
// Always define columns in a separate file
export const columns: ColumnDef<Recipient>[] = [
  // 1. Select column (pinned left)
  { id: 'select', size: 40, enableHiding: false, header: SelectAllCheckbox, cell: SelectRowCheckbox },

  // 2. Data columns with sorting
  {
    accessorKey: 'email',
    header: ({ column }) => <SortButton column={column}>Email</SortButton>,
    cell: ({ row }) => <code>{row.original.email}</code>,
  },

  // 3. Editable columns
  {
    accessorKey: 'department',
    cell: ({ row, table }) => (
      <EditableCell
        value={row.original.department}
        onSave={(val) => table.options.meta?.onUpdateField(row.original.id, 'department', val)}
      />
    ),
  },

  // 4. Multi-select filter columns
  {
    accessorKey: 'status',
    filterFn: (row, id, values: string[]) => !values?.length || values.includes(row.getValue(id)),
  },

  // 5. Actions column (pinned right)
  { id: 'actions', enableHiding: false, cell: ActionsDropdown },
]
```

**Form Pattern:**
```typescript
const form = useForm<CreateRecipientInput>({
  resolver: zodResolver(CreateRecipientSchema),
  defaultValues: { email: '', firstName: '', lastName: '', status: 'active' },
})

const createMutation = useCreateRecipient()

const onSubmit = (data: CreateRecipientInput) => {
  createMutation.mutate(data, {
    onSuccess: () => {
      toast.success('Recipient created')
      form.reset()
    },
    onError: (err) => toast.error(err.message),
  })
}
```

**Rules:**
- ALWAYS use UnifiedDataTable for list views (never raw TanStack Table)
- Columns in separate file from the data table component
- Forms use react-hook-form + Zod (ALWAYS)
- Toast notifications for all mutations (success + error)
- Sidepanel for details (not separate pages, unless complex)

### Phase 4: Pages

Wire everything together in App Router pages:

```
src/app/[locale]/(workspace)/{feature}/
  ├── page.tsx          # List page
  ├── [id]/page.tsx     # Detail page (if needed)
  └── layout.tsx        # Feature layout (if needed)
```

```typescript
// src/app/[locale]/(workspace)/recipients/page.tsx
'use client'

import { useRecipients } from '@/features/recipients/hooks'
import { RecipientsDataTable } from '@/features/recipients/components'
import { PageHeader } from '@/components/common'

export default function RecipientsPage() {
  const { data: recipients, isLoading } = useRecipients()

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader
        title="Recipients"
        description="Manage your recipient list"
        actions={<Button onClick={() => setShowCreate(true)}>Add Recipient</Button>}
      />
      <RecipientsDataTable data={recipients ?? []} isLoading={isLoading} />
    </div>
  )
}
```

**Rules:**
- Pages are thin wrappers (fetch data → render components)
- Use `'use client'` for pages with hooks/state
- Use `PageHeader` component for consistent page headers
- Loading states handled by component (skeleton/spinner)

### Phase 5: Wizard Patterns (Complex Features)

For multi-step workflows (import, create campaign, onboarding):

```
src/features/{feature}/components/
  ├── {feature}-wizard.tsx          # Wizard container + state
  ├── steps/
  │   ├── step-upload.tsx           # Step 1
  │   ├── step-configure.tsx        # Step 2
  │   └── step-review.tsx           # Step 3
  └── utils/
      ├── auto-mapper.ts            # Complex logic (separate file)
      └── chunked-processor.ts      # Performance utilities
```

**Wizard State Pattern (from CSV import reference):**
```typescript
interface WizardState {
  step: 1 | 2 | 3
  // Step 1 data
  file: File | null
  parsedData: Record<string, string>[]
  // Step 2 data
  fieldMappings: FieldMapping[]
  duplicateHandling: 'skip' | 'update'
  // Step 3 data
  isImporting: boolean
  importProgress: number
}

// Single source of truth — passed to all steps via props
function Wizard() {
  const [state, setState] = useState<WizardState>(initialState)
  const updateState = (partial: Partial<WizardState>) => setState(prev => ({ ...prev, ...partial }))

  return state.step === 1 ? <StepUpload state={state} updateState={updateState} /> :
         state.step === 2 ? <StepConfigure state={state} updateState={updateState} /> :
         <StepReview state={state} updateState={updateState} />
}
```

**Chunked Processing (for large datasets):**
```typescript
// MANDATORY for >1000 rows — prevents UI freezing
async function processInChunks<T, R>(config: {
  data: T[]
  chunkSize: number
  processor: (chunk: T[], startIndex: number) => R[]
  onProgress: (percent: number) => void
}): Promise<R[]> {
  const results: R[] = []
  for (let i = 0; i < config.data.length; i += config.chunkSize) {
    const chunk = config.data.slice(i, i + config.chunkSize)
    results.push(...config.processor(chunk, i))
    config.onProgress(Math.round(((i + chunk.length) / config.data.length) * 100))
    await new Promise(resolve => setTimeout(resolve, 0)) // Yield to UI thread
  }
  return results
}
```

**Rules:**
- Wizard state is a SINGLE object (not scattered useState calls)
- Each step is its own component receiving state + updateState
- Complex logic (auto-mapping, duplicate detection) in separate utils files
- Chunked processing for any operation on >1000 items
- Progress tracking for long operations

### Phase 6: Polish & Quality

Before considering any feature "done":

**Checklist:**
- [ ] Types defined in `types.ts` (no `any` anywhere)
- [ ] Mock data is realistic (Indian names, real departments, proper dates)
- [ ] API service covers all CRUD + bulk operations
- [ ] React Query hooks with proper key hierarchy
- [ ] UnifiedDataTable with: search, filters, bulk actions, column persistence
- [ ] Forms with Zod validation + proper error messages
- [ ] Toast notifications for all mutations
- [ ] Loading states (skeleton/spinner) for async data
- [ ] Empty states for no data
- [ ] Error states for failed fetches
- [ ] Responsive design (works on mobile)
- [ ] Keyboard accessible (tab navigation, enter to submit)
- [ ] No console errors/warnings

## State Management Decision Tree

```
Is this data from an API?
├── YES → TanStack Query (useQuery/useMutation)
│         Never put API data in Zustand.
│
└── NO → Is it shared across many components?
         ├── YES → Zustand store (with persist if needed)
         │         Examples: sidebar state, user preferences, active workspace
         │
         └── NO → Is it form state?
                  ├── YES → react-hook-form (useForm)
                  │
                  └── NO → React useState/useReducer
                           Examples: modal open, local filter, wizard step
```

## Feature Module Template

```
src/features/{name}/
├── index.ts                    # Barrel exports
├── types.ts                    # Entity types + Zod schemas
├── lib/
│   ├── api.ts                  # API service (recipientsApi)
│   └── index.ts
├── hooks/
│   ├── use-{name}.ts           # React Query hooks
│   └── index.ts
└── components/
    ├── {name}-data-table.tsx    # Table wrapper
    ├── {name}-columns.tsx       # Column definitions
    ├── {name}-form.tsx          # Create/edit form
    ├── {name}-detail.tsx        # Detail view
    └── index.ts
```

## MSSP / Multi-Tenant Frontend Patterns

Every frontend feature must work for three customer types. Use **progressive complexity** — UC1 users see a simple UI, UC3 users see the full feature set.

### Workspace Context (Required for UC3)

```typescript
// Zustand store — persists active workspace
interface WorkspaceState {
  activeWorkspaceId: string | null
  activeCompanyId: string | null
  workspaces: Workspace[]
  setActiveWorkspace: (id: string) => void
}

// Every fetchApi() call includes workspace header automatically
headers: { 'x-workspace-id': useWorkspaceStore.getState().activeWorkspaceId }
```

**Rules:**
- Workspace selector in top nav (HIDDEN when company has only 1 workspace)
- "All Workspaces" option for Company Admins (read-only aggregated view)
- Switching workspace refreshes ALL React Query caches: `queryClient.invalidateQueries()`

### Domain Tabs (Required for UC2+)

```typescript
// Domain tabs above data table — NOT a cosmetic filter
<DomainTabs
  domains={workspaceDomains}        // Fetched from /api/domains
  activeDomainId={activeDomainId}   // null = "All Domains"
  onSelect={(domainId) => setActiveDomainId(domainId)}
/>

// Passes domainId to API: /api/recipients?domainId=xxx
```

**Rules:**
- HIDDEN when workspace has only 1 domain (UC1)
- Shows recipient count per domain
- "All Domains" tab shows combined (with Person de-dup count)

### Person Column (Required for UC2+)

```typescript
// In column definitions
{
  id: 'person',
  header: 'Person',
  cell: ({ row }) => {
    const linkCount = row.original.personLinkCount
    return linkCount > 1
      ? <Badge variant="outline">{linkCount} identities</Badge>
      : <span className="text-muted-foreground">Single</span>
  },
  // HIDDEN when workspace has only 1 domain (UC1)
}
```

### Bulk Operations Domain Breakdown (Required for UC2+)

```typescript
// When selecting across domains, show breakdown in toolbar
<BulkActionsToolbar>
  <span>5 from tatasteel.com, 3 from tatasteel.co.in selected</span>
  {hasSyncProtectedFields && (
    <Alert variant="warning">
      3 recipients have sync-protected fields. Changes may revert on next sync.
    </Alert>
  )}
</BulkActionsToolbar>
```

### Settings Inheritance UI (Required for UC3)

```typescript
// Each settings field shows its source
<SettingsField
  label="Track Email Opens"
  value={settings.trackOpens}
  source={fieldSources.trackOpens}  // 'company' | 'workspace' | 'override'
  onOverride={() => /* unlock field for workspace-level edit */}
  onReset={() => /* reset to company default */}
/>

// Badges: COMPANY (green, locked) | WORKSPACE (blue) | OVERRIDE (yellow, unlockable)
```

### Progressive Complexity Rule

```typescript
// In any component that has UC3-specific features:
const { workspaces } = useWorkspaceStore()
const { domains } = useDomainsForWorkspace(activeWorkspaceId)

const showWorkspaceSelector = workspaces.length > 1
const showDomainTabs = domains.length > 1
const showPersonColumn = domains.length > 1 || workspaces.length > 1
const showCompanyLibrary = workspaces.length > 1
const showBlueprintFeatures = workspaces.length > 1
const showSettingsInheritance = workspaces.length > 1

// UC1 user sees NONE of these. UC3 sees ALL.
```

### MSSP Frontend Checklist

- [ ] Workspace selector exists (hidden for UC1)
- [ ] Domain tabs exist (hidden when 1 domain)
- [ ] Person column exists (hidden when 1 domain)
- [ ] `fetchApi()` sends `x-workspace-id` header automatically
- [ ] Switching workspace invalidates all React Query caches
- [ ] "All Workspaces" view is read-only for Company Admin
- [ ] Bulk ops show domain breakdown
- [ ] Sync-protected field warnings for synced recipients
- [ ] Import wizard asks for target domain (hidden when 1 domain)
- [ ] Settings show COMPANY/WORKSPACE/OVERRIDE badges
- [ ] Progressive complexity: UC1 sees simple UI, UC3 sees full

## Master Checklist — Run Before Shipping

**Types & Data:**
- [ ] All types in `types.ts` (no inline types)
- [ ] Zod schemas for all form inputs
- [ ] API service with typed methods
- [ ] Mock data handler added to router

**State:**
- [ ] React Query for server state (NEVER Zustand for API data)
- [ ] Query keys follow hierarchical pattern
- [ ] Mutations invalidate correct queries
- [ ] Zustand only for client-only state (UI prefs, sidebar)

**Components:**
- [ ] UnifiedDataTable for all list views
- [ ] Columns in separate file
- [ ] Forms use react-hook-form + Zod
- [ ] Editable cells for inline editing
- [ ] Bulk actions with confirmation dialogs

**UX:**
- [ ] Loading skeletons (not spinners)
- [ ] Empty states with action buttons
- [ ] Error states with retry
- [ ] Toast on every mutation
- [ ] Optimistic updates where appropriate

**Performance:**
- [ ] Chunked processing for >1000 items
- [ ] No `any` types
- [ ] No unnecessary re-renders (memo where needed)
- [ ] Images use next/image
