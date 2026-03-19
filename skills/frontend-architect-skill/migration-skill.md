# Frontend Migration Skill

## Purpose

Migrate ANY Next.js frontend from a flat/legacy structure to the correct feature-module architecture defined in `SKILL.md`. This is a generic, pattern-based migration — not tied to any specific project.

## When to Use

Trigger this skill when:
- A Next.js project has all components in one flat `components/` directory
- Types are scattered instead of co-located with features
- No centralized API layer exists (raw `fetch()` in components/pages)
- No React Query hooks (data fetched via `useEffect` + `useState`)
- No Zustand stores (all state in component-level `useState`)
- No route groups (`(auth)`, `(workspace)`)
- No `src/` directory (code at root level)
- No feature modules (`features/{name}/types.ts + lib/ + hooks/ + components/`)

## Diagnosis Checklist

Before migrating, assess the current project. Check each box:

| # | Check | Healthy | Needs Fix |
|---|-------|---------|-----------|
| 1 | Has `src/` directory? | Source code in `src/` | Code at root level |
| 2 | `tsconfig` alias `@/*` → `./src/*`? | Correct alias | Points to `./` or wrong path |
| 3 | Has `features/` directory? | Vertical feature slices | Everything in flat `components/` |
| 4 | Types co-located with features? | `features/{name}/types.ts` | Types in `lib/types/` or inline |
| 5 | Has `lib/api/client.ts`? | Centralized `fetchApi()` | Raw `fetch()` scattered |
| 6 | Has React Query hooks? | `useQuery`/`useMutation` per feature | `useEffect` + `fetch` + `useState` |
| 7 | Has Zustand stores? | `stores/ui-store.ts`, `stores/user-store.ts` | All state in `useState` |
| 8 | Has route groups? | `(auth)`, `(workspace)`, `(error)` | Flat routes |
| 9 | Has middleware? | Auth + i18n middleware | No `middleware.ts` |
| 10 | Has mock/real adapter? | `lib/api/mode.ts` switches modes | Hardcoded to one mode |

**Score:** Count "Needs Fix" items. That's your migration scope.

## Migration Phases

### CRITICAL: Order Matters

```
Phase 1: src/ directory + tsconfig (foundation — everything depends on this)
Phase 2: Feature modules (organize code into vertical slices)
Phase 3: API layer + React Query (replace raw fetch with caching)
Phase 4: Zustand stores (extract global client state)
Phase 5: Route groups + layouts (organize navigation)
Phase 6: Auth + middleware (add security)
Phase 7: i18n (add internationalization — optional)
```

Each phase is independently deployable. The app keeps working after each phase.

---

## Phase 1: Source Directory + Aliases

**Goal:** Establish `src/` as the source boundary.

**Steps:**
1. Create `src/` directory
2. Move all source folders into it: `app/`, `components/`, `hooks/`, `lib/`, `data/` (if exists)
3. Update `tsconfig.json`:
   ```json
   { "compilerOptions": { "paths": { "@/*": ["./src/*"] } } }
   ```
4. Update `components.json` (shadcn) aliases to point to `@/components`, `@/lib/utils`, etc.
5. Verify all imports resolve. Run `npm run build`.

**Verification:** Zero import errors. Dev server starts. All pages render.

---

## Phase 2: Feature Modules

**Goal:** Move from flat `components/` to vertical feature slices.

**Target structure per feature:**
```
src/features/{feature-name}/
├── index.ts                    # Barrel exports
├── types.ts                    # Entity types + Zod schemas
├── lib/
│   ├── api.ts                  # Feature API service
│   └── index.ts
├── hooks/
│   ├── use-{feature-name}.ts   # React Query hooks
│   └── index.ts
└── components/
    ├── {feature}-data-table.tsx # Table wrapper
    ├── {feature}-columns.tsx    # Column definitions
    ├── {feature}-form.tsx       # Create/edit form
    ├── {feature}-detail.tsx     # Detail view
    └── index.ts
```

**Migration rules:**
1. **Identify features:** Each major page/route is a feature. If `app/recipients/` exists, `recipients` is a feature.
2. **Create feature directory** with the template structure above.
3. **Move types:** Find all type files related to this feature. Merge into `features/{name}/types.ts`. Include Zod schemas.
4. **Move components:** Move feature-specific components from `components/{name}/` to `features/{name}/components/`.
5. **Keep shared components:** `components/ui/` (shadcn), `components/layouts/`, `components/common/` stay where they are.
6. **Create barrel exports:** Every `index.ts` re-exports the public API of that module.
7. **Update imports:** Use IDE refactoring. Every import path must resolve.

**What stays in `components/`:**
- `components/ui/` — shadcn/ui atomic components
- `components/common/` — shared molecules (PageHeader, StatCard, ErrorBoundary)
- `components/layouts/` — app shell (Sidebar, Header, Nav)
- `components/common/providers/` — React context providers

**What moves to `features/`:**
- Any component directory that maps 1:1 to a route/page
- Feature-specific types, hooks, API services

---

## Phase 3: API Layer + React Query

**Goal:** Replace raw `fetch()` + `useEffect` with centralized API client + React Query.

### Step 1: Create API Client

```
src/lib/api/
├── client.ts       # fetchApi<T>() — client-side, handles mock/real
├── server.ts       # apiFetch<T>() — server-side with auth headers
├── mode.ts         # getApiMode(), setApiMode(), isMockMode()
├── mock/
│   ├── handler.ts  # Routes mock requests to data
│   └── index.ts
└── index.ts
```

**`fetchApi()` template:**
```typescript
export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const mode = getApiMode() // 'mock' | 'real'

  if (mode === 'mock') {
    const { handleMockRequest } = await import('./mock/handler')
    return handleMockRequest<T>(endpoint, options)
  }

  const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
  })

  if (!response.ok) {
    throw new ApiClientError(response.status, await response.text())
  }

  return response.json()
}
```

### Step 2: Create Feature API Services

**Template:**
```typescript
// src/features/{name}/lib/api.ts
import { fetchApi, buildQueryString } from '@/lib/api'
import type { Entity, EntityFilter, CreateEntityInput } from '../types'

export const {name}Api = {
  list:      (filter?: EntityFilter) => fetchApi<Entity[]>(`/api/{name}${buildQueryString(filter)}`),
  getById:   (id: string)           => fetchApi<Entity>(`/api/{name}/${id}`),
  create:    (data: CreateEntityInput) => fetchApi<Entity>(`/api/{name}`, { method: 'POST', body: JSON.stringify(data) }),
  update:    (id: string, data: Partial<Entity>) => fetchApi<Entity>(`/api/{name}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete:    (id: string)           => fetchApi<void>(`/api/{name}/${id}`, { method: 'DELETE' }),
  bulkDelete:(ids: string[])        => fetchApi(`/api/{name}/bulk-delete`, { method: 'POST', body: JSON.stringify({ ids }) }),
}
```

### Step 3: Create React Query Hooks

**Template:**
```typescript
// src/features/{name}/hooks/use-{name}.ts
export const {name}Keys = {
  all:     ['{name}'] as const,
  lists:   () => [...{name}Keys.all, 'list'] as const,
  list:    (filter?: EntityFilter) => [...{name}Keys.lists(), filter] as const,
  details: () => [...{name}Keys.all, 'detail'] as const,
  detail:  (id: string) => [...{name}Keys.details(), id] as const,
}

export function use{Name}s(filter?: EntityFilter) {
  return useQuery({ queryKey: {name}Keys.list(filter), queryFn: () => {name}Api.list(filter) })
}

export function useCreate{Name}() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: {name}Api.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: {name}Keys.lists() }),
  })
}
```

### Step 4: Migrate Pages

**Find and replace pattern:**

BEFORE:
```typescript
const [data, setData] = useState([])
const [loading, setLoading] = useState(true)
useEffect(() => {
  fetch('/api/{name}').then(r => r.json()).then(d => { setData(d); setLoading(false) })
}, [])
```

AFTER:
```typescript
const { data, isLoading } = use{Name}s()
```

---

## Phase 4: Zustand Stores

**Goal:** Extract global client-side state into Zustand.

**Create these stores:**

```
src/stores/
├── ui-store.ts         # Sidebar, modals, command palette
├── workspace-store.ts  # Active workspace/company context (for multi-tenant)
├── user-store.ts       # User preferences (date format, compact mode)
└── index.ts
```

**Template:**
```typescript
import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

interface UIState {
  sidebarCollapsed: boolean
  activeModal: string | null
  toggleSidebar: () => void
  openModal: (id: string) => void
  closeModal: () => void
}

export const useUIStore = create<UIState>()(
  devtools(
    persist(
      (set) => ({
        sidebarCollapsed: false,
        activeModal: null,
        toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
        openModal: (id) => set({ activeModal: id }),
        closeModal: () => set({ activeModal: null }),
      }),
      { name: 'ui-storage', partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed }) }
    ),
    { name: 'UIStore' }
  )
)
```

**Decision tree for what goes in Zustand vs elsewhere:**
- API data → React Query (NEVER Zustand)
- Form state → react-hook-form
- Global UI state (sidebar, modals) → Zustand
- User preferences (persisted) → Zustand with `persist`
- Workspace context → Zustand with `persist`
- Component-local state → `useState`

---

## Phase 5: Route Groups

**Goal:** Organize routes with `(auth)`, `(workspace)`, `(error)` groups.

**Template:**
```
src/app/
├── layout.tsx              # Minimal: HTML, fonts, providers
├── page.tsx                # Redirect to default route
├── api/                    # API routes (keep flat)
├── (workspace)/            # Protected routes
│   ├── layout.tsx          # Sidebar + header + workspace context
│   ├── {feature}/          # Feature routes
│   └── settings/
├── (auth)/                 # Public auth routes
│   ├── layout.tsx          # Card-based layout
│   └── login/
└── (error)/                # Error pages
    ├── 401/
    └── 500/
```

**Rule:** API routes (`app/api/`) are NEVER inside route groups.

---

## Phase 6: Auth + Middleware

**Goal:** Add Better Auth and route protection.

**Files to create:**
```
src/lib/auth/auth.ts          # betterAuth() server config
src/lib/auth/auth-client.ts   # createAuthClient() for client
src/app/api/auth/[...all]/route.ts  # Auth handler
src/middleware.ts              # Route protection
```

**Middleware template:**
```typescript
export default function middleware(request: NextRequest) {
  const isAuthRoute = request.nextUrl.pathname.startsWith('/login')
  const isApiRoute = request.nextUrl.pathname.startsWith('/api')
  const hasSession = request.cookies.has('better-auth.session_token')

  if (isApiRoute) return NextResponse.next()
  if (isAuthRoute && hasSession) return NextResponse.redirect(new URL('/dashboard', request.url))
  if (!isAuthRoute && !hasSession) return NextResponse.redirect(new URL('/login', request.url))

  return NextResponse.next()
}
```

---

## Phase 7: i18n (Optional)

**Goal:** Add next-intl for multi-language support.

**Files to create:**
```
src/i18n/routing.ts       # Locale config
src/i18n/request.ts       # Request-side setup
src/locales/en/common.json
```

**This adds `[locale]` segment to all routes.** Only do this if multi-language is a requirement.

---

## Anti-Patterns to Fix During Migration

| Anti-Pattern | Fix |
|-------------|-----|
| `fetch()` in `useEffect` | Replace with React Query `useQuery` |
| `useState` for API data | Replace with React Query |
| `useState` for global state | Replace with Zustand store |
| Types in `lib/types/` | Move to `features/{name}/types.ts` |
| All components in `components/` | Split into `features/` + `components/` |
| No barrel exports | Add `index.ts` to every module |
| `any` types | Replace with proper TypeScript types |
| `?limit=10000` (fetch all) | Replace with server-side pagination |
| No loading states | Add skeleton/spinner via React Query `isLoading` |
| No error states | Add error handling via React Query `isError` |

## Preserved Assets

During migration, NEVER rewrite these — they are production-grade:

1. **UnifiedDataTable** — move to `features/{name}/components/ui/`, don't modify
2. **CSV Import Wizard** — move to `features/{name}/components/import/`, don't modify
3. **Auto-Mapper** — move to `features/{name}/components/import/utils/`, don't modify
4. **All shadcn/ui components** — stay in `components/ui/`, don't modify
5. **Zod schemas** — merge into `features/{name}/types.ts`, don't rewrite
