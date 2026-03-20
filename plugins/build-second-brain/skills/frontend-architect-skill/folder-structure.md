# Folder Structure Reference

## Complete Project Layout

```
src/
├── app/                              # Next.js App Router
│   ├── layout.tsx                    # Root layout (HTML, fonts)
│   ├── globals.css                   # Theme variables + Tailwind
│   ├── not-found.tsx                 # 404 page
│   ├── global-error.tsx              # Error boundary
│   ├── api/                          # API routes
│   │   ├── auth/[...all]/route.ts    # Better Auth handler
│   │   └── {feature}/route.ts        # Feature API routes
│   └── [locale]/                     # Locale-parameterized routes
│       ├── layout.tsx                # i18n + providers
│       ├── (auth)/                   # Public auth pages
│       │   ├── layout.tsx            # Card-based layout
│       │   ├── login/page.tsx
│       │   ├── register/page.tsx
│       │   └── ...
│       ├── (workspace)/              # Protected pages
│       │   ├── layout.tsx            # Sidebar + header layout
│       │   ├── dashboard/page.tsx
│       │   ├── recipients/page.tsx
│       │   ├── campaigns/page.tsx
│       │   └── ...
│       └── (error)/                  # Error pages
│           ├── 401/page.tsx
│           └── 500/page.tsx
│
├── components/                       # Shared UI components
│   ├── ui/                           # shadcn/ui atoms (61+)
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── form.tsx
│   │   ├── dialog.tsx
│   │   └── ...
│   ├── common/                       # Feature-agnostic molecules
│   │   ├── providers/
│   │   │   ├── auth-provider.tsx
│   │   │   └── query-provider.tsx
│   │   ├── page-header.tsx
│   │   ├── stat-card.tsx
│   │   ├── data-table/               # Base data table (if not using unified)
│   │   ├── error-boundary.tsx
│   │   └── language-switcher.tsx
│   └── layouts/                      # Layout organisms
│       ├── app-sidebar.tsx
│       ├── app-header.tsx
│       ├── theme-provider.tsx
│       ├── nav-main.tsx
│       └── team-switcher.tsx
│
├── features/                         # Feature modules (vertical slices)
│   ├── recipients/                   # Each feature follows this structure:
│   │   ├── index.ts                  # Barrel exports
│   │   ├── types.ts                  # Types + Zod schemas
│   │   ├── lib/
│   │   │   ├── api.ts                # API service (recipientsApi)
│   │   │   └── index.ts
│   │   ├── hooks/
│   │   │   ├── use-recipients.ts     # React Query hooks
│   │   │   └── index.ts
│   │   └── components/
│   │       ├── recipients-data-table.tsx
│   │       ├── recipients-columns.tsx
│   │       ├── recipients-form.tsx
│   │       ├── recipients-detail.tsx
│   │       └── index.ts
│   ├── campaigns/                    # Same structure
│   ├── training/                     # Same structure
│   ├── announcements/                # Same structure
│   ├── settings/                     # Same structure
│   └── ...
│
├── lib/                              # Core utilities & services
│   ├── api/                          # API adapter layer
│   │   ├── client.ts                 # fetchApi() — client-side
│   │   ├── server.ts                 # apiFetch() — server-side
│   │   ├── mode.ts                   # Mock/real switching
│   │   └── mock/                     # Mock data & handlers
│   │       ├── handler.ts            # Request router
│   │       ├── recipients.ts         # Mock recipients
│   │       ├── campaigns.ts          # Mock campaigns
│   │       └── index.ts
│   ├── auth/                         # Better Auth config
│   │   ├── auth.ts                   # Server config
│   │   └── auth-client.ts            # Client config
│   ├── utils.ts                      # cn() utility
│   ├── env.ts                        # Env validation (Zod)
│   └── constants/
│       └── themes.ts
│
├── stores/                           # Zustand stores (client-only state)
│   ├── ui-store.ts                   # Sidebar, modals, command palette
│   ├── user-store.ts                 # Preferences (persisted)
│   └── index.ts
│
├── hooks/                            # Global custom hooks
│   ├── use-mobile.ts
│   └── use-theme-settings.tsx
│
├── types/                            # Global shared types
│   └── index.ts                      # ApiResponse<T>, User, NavItem
│
├── i18n/                             # Internationalization config
│   ├── routing.ts
│   ├── request.ts
│   └── navigation.ts
│
├── locales/                          # Translation files
│   ├── en/common.json
│   ├── es/common.json
│   ├── ar/common.json
│   └── ...
│
├── config/                           # App configuration
│   └── site.ts
│
└── middleware.ts                      # Auth + i18n middleware
```

## Key Rules

1. **Features are vertical slices** — each feature owns its types, API, hooks, and components
2. **Components are horizontal** — shared UI components live in `components/ui/` and `components/common/`
3. **Lib is infrastructure** — API client, auth, utils — no feature logic here
4. **Stores are global only** — feature-specific state uses React Query or local state
5. **Types bubble up** — feature types in `features/x/types.ts`, shared types in `types/index.ts`
6. **Pages are thin** — just import from features, wire up data, render components
7. **Mock data lives in `lib/api/mock/`** — separate from feature code
