# Frontend Performance — Bundle Analysis, React Profiling, Virtualization, Lazy Loading

> Read this file when optimizing page load times, reducing bundle size, fixing rendering
> performance, setting up virtualization for large tables, or configuring Lighthouse CI.

---

## Table of Contents

1. [Bundle Size Optimization](#bundle-size-optimization)
2. [React Rendering Optimization](#react-rendering-optimization)
3. [Server-Side Pagination](#server-side-pagination)
4. [Table Virtualization](#table-virtualization)
5. [TanStack Query Optimization](#tanstack-query-optimization)
6. [Image Optimization](#image-optimization)
7. [Code Splitting and Lazy Loading](#code-splitting-and-lazy-loading)
8. [Lighthouse CI Setup](#lighthouse-ci-setup)

---

## Bundle Size Optimization

### next/bundle-analyzer Setup

```typescript
// next.config.ts
import withBundleAnalyzer from '@next/bundle-analyzer';

const config = withBundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
})({
  // ... your existing Next.js config
});

export default config;
```

```bash
# Run analysis
ANALYZE=true npm run build
# Opens browser with interactive treemap of all bundles
```

### What to Look For in Bundle Output

| Red Flag | Impact | Fix |
|----------|--------|-----|
| Any single chunk > 200KB gzip | Slow initial load | Code split with `dynamic()` |
| `moment` or `moment-timezone` | ~300KB uncompressed | Replace with `date-fns` or `dayjs` |
| Full `lodash` import | ~70KB | Use `lodash-es` or import individual functions |
| Full icon library (e.g., `@heroicons/react`) | ~200KB+ | Import only used icons |
| Duplicate packages across chunks | Wasted bytes | Check with `npm ls <pkg>`, dedupe |
| `node_modules` code in client bundle | Server code leaking | Check imports, use `server-only` package |
| Large charting library in main chunk | Blocks LCP | `dynamic(() => import('./Chart'))` |

### Tree-Shaking Verification

```typescript
// BAD: Imports entire library — bundler cannot tree-shake
import { format, parse, addDays, subDays, isAfter, isBefore } from 'date-fns';

// GOOD: Direct imports — only includes what you use
import { format } from 'date-fns/format';
import { addDays } from 'date-fns/addDays';

// BAD: Barrel import pulls everything
import { Button, Input, Table, Modal, Tooltip } from '@/components/ui';

// GOOD: Direct import (if barrel re-exports cause large bundles)
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
```

### Dependency Audit

```bash
# Find the largest packages in your bundle
npx depcheck          # find unused dependencies
npx cost-of-modules   # show install size of each dependency
```

**Common replacements for oversized packages:**

| Heavy Package | Size | Replacement | Size |
|--------------|------|-------------|------|
| `moment` | 290KB | `date-fns` | 12KB (tree-shaken) |
| `lodash` | 71KB | `lodash-es` (tree-shaken) | ~5KB typical |
| `axios` | 14KB | `fetch` (built-in) | 0KB |
| `classnames` | 1KB | `clsx` | 0.5KB |
| `uuid` | 3KB | `crypto.randomUUID()` | 0KB |

### Analyzing Shared Chunks

```bash
# Check what is in your shared/commons chunk
# In the bundle analyzer output, look for:
# - vendor-shared: packages used by multiple routes
# - commons: code shared between pages
# If vendor-shared > 100KB, investigate what is pulling in large deps
```

---

## React Rendering Optimization

### Identifying Unnecessary Re-Renders

**Step 1: React DevTools Profiler**

1. Open React DevTools in browser
2. Go to Profiler tab
3. Click "Record"
4. Perform the action you want to profile
5. Click "Stop"
6. Look for components that re-render but produce the same output

**Step 2: Why Did You Render (development only)**

```typescript
// Only in development — remove before production
// _app.tsx or layout.tsx
if (process.env.NODE_ENV === 'development') {
  const { default: whyDidYouRender } = await import(
    '@welldone-software/why-did-you-render'
  );
  whyDidYouRender(React, {
    trackAllPureComponents: true,
    logOnDifferentValues: true,
  });
}
```

### React.memo for Expensive Components

```typescript
// BAD: Re-renders on every parent render, even if props are unchanged
function RecipientRow({ recipient, onSelect }: RecipientRowProps) {
  return (
    <tr>
      <td>{recipient.email}</td>
      <td>{recipient.firstName}</td>
      <td><button onClick={() => onSelect(recipient.id)}>Select</button></td>
    </tr>
  );
}

// GOOD: Only re-renders when props actually change
const RecipientRow = React.memo(function RecipientRow({
  recipient,
  onSelect,
}: RecipientRowProps) {
  return (
    <tr>
      <td>{recipient.email}</td>
      <td>{recipient.firstName}</td>
      <td><button onClick={() => onSelect(recipient.id)}>Select</button></td>
    </tr>
  );
});

// CRITICAL: React.memo is useless if you pass a new object/function every render.
// The parent must stabilize props:
function RecipientTable({ recipients }: Props) {
  // Stable callback — does not create a new function every render
  const handleSelect = useCallback((id: string) => {
    setSelected(id);
  }, []);

  return recipients.map((r) => (
    <RecipientRow key={r.id} recipient={r} onSelect={handleSelect} />
  ));
}
```

### useMemo for Derived Data

```typescript
// BAD: Recomputes on every render
function RecipientList({ recipients, filter }: Props) {
  const filtered = recipients.filter((r) =>
    r.email.includes(filter) || r.firstName.includes(filter),
  );
  const sorted = filtered.sort((a, b) => a.email.localeCompare(b.email));
  // ...
}

// GOOD: Only recomputes when dependencies change
function RecipientList({ recipients, filter }: Props) {
  const processedRecipients = useMemo(() => {
    const filtered = recipients.filter((r) =>
      r.email.includes(filter) || r.firstName.includes(filter),
    );
    return filtered.sort((a, b) => a.email.localeCompare(b.email));
  }, [recipients, filter]);
  // ...
}
```

### Context Splitting

```typescript
// BAD: Single context with mixed update frequencies
const AppContext = createContext<{
  user: User;          // Changes rarely (login/logout)
  theme: Theme;        // Changes rarely (settings)
  sidebarOpen: boolean; // Changes frequently (click)
  notifications: Notification[]; // Changes frequently (real-time)
}>({...});
// Every sidebar toggle re-renders ALL consumers, including those
// that only need user data.

// GOOD: Split by update frequency
const AuthContext = createContext<{ user: User }>({...});
const ThemeContext = createContext<{ theme: Theme }>({...});
const UIContext = createContext<{ sidebarOpen: boolean }>({...});
const NotificationContext = createContext<{ notifications: Notification[] }>({...});

// Components subscribe only to what they need:
function UserAvatar() {
  const { user } = useContext(AuthContext); // Does not re-render on sidebar toggle
  return <Avatar src={user.avatar} />;
}
```

### TanStack Table Column Memoization

```typescript
// BAD: New column definitions on every render
function RecipientsTable({ data }: Props) {
  const columns = [
    columnHelper.accessor('email', { header: 'Email' }),
    columnHelper.accessor('firstName', { header: 'First Name' }),
    // ... 10 more columns
  ];
  // TanStack Table recalculates everything because columns array is new

  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() });
}

// GOOD: Memoize column definitions
function RecipientsTable({ data }: Props) {
  const columns = useMemo(() => [
    columnHelper.accessor('email', { header: 'Email' }),
    columnHelper.accessor('firstName', { header: 'First Name' }),
    // ... 10 more columns
  ], []); // Empty deps — columns are static

  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() });
}
```

---

## Server-Side Pagination

### Why Client-Side Pagination Fails at Scale

With 35,000 records in a single workspace:
- Fetching all rows: ~7MB JSON payload, ~2s network transfer
- Parsing: ~500ms JSON.parse on main thread
- Memory: ~35MB in browser heap
- Rendering: table component tries to process 35K rows

### Server-Side Pagination with TanStack Query

```typescript
// hooks/useRecipientList.ts
interface UseRecipientListParams {
  domainId: string;
  page: number;
  pageSize: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  filters?: Record<string, string>;
}

export function useRecipientList(params: UseRecipientListParams) {
  const { domainId, page, pageSize, sortBy, sortOrder, filters } = params;

  return useQuery({
    queryKey: ['recipients', 'list', domainId, { page, pageSize, sortBy, sortOrder, filters }],
    queryFn: () =>
      api.recipients.list({
        domainId,
        page,
        limit: pageSize,
        sortBy,
        sortOrder,
        ...filters,
      }),
    placeholderData: keepPreviousData, // Keep showing old data while new page loads
    staleTime: 30_000,
  });
}

// components/RecipientsTable.tsx
function RecipientsTable({ domainId }: Props) {
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });
  const [sorting, setSorting] = useState<SortingState>([]);

  const { data, isLoading, isFetching } = useRecipientList({
    domainId,
    page: pagination.pageIndex + 1, // API is 1-indexed
    pageSize: pagination.pageSize,
    sortBy: sorting[0]?.id,
    sortOrder: sorting[0]?.desc ? 'desc' : 'asc',
  });

  const table = useReactTable({
    data: data?.data ?? [],
    columns,
    pageCount: Math.ceil((data?.meta?.total ?? 0) / pagination.pageSize),
    state: { pagination, sorting },
    onPaginationChange: setPagination,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,  // Server handles pagination
    manualSorting: true,     // Server handles sorting
  });

  return (
    <div>
      {isFetching && <LoadingOverlay />}
      <Table table={table} />
      <PaginationControls table={table} total={data?.meta?.total} />
    </div>
  );
}
```

### Prefetching the Next Page

```typescript
// Prefetch the next page when user is on current page
const queryClient = useQueryClient();

useEffect(() => {
  if (data?.meta?.hasMore) {
    queryClient.prefetchQuery({
      queryKey: ['recipients', 'list', domainId, {
        page: pagination.pageIndex + 2, // next page (1-indexed)
        pageSize: pagination.pageSize,
        sortBy: sorting[0]?.id,
        sortOrder: sorting[0]?.desc ? 'desc' : 'asc',
      }],
      queryFn: () =>
        api.recipients.list({
          domainId,
          page: pagination.pageIndex + 2,
          limit: pagination.pageSize,
        }),
    });
  }
}, [data, pagination, sorting, domainId, queryClient]);
```

---

## Table Virtualization

### When to Virtualize

| Row Count | Approach | Reason |
|-----------|----------|--------|
| < 100 | Render all | No performance concern |
| 100-500 | Render all with `React.memo` rows | Minor optimization |
| 500-5,000 | Virtualize | DOM node count causes jank |
| 5,000-50,000 | Virtualize + server-side pagination | Must limit data in memory |
| > 50,000 | Server-side pagination only | Never load this many rows |

### TanStack Table + TanStack Virtual

```typescript
import { useVirtualizer } from '@tanstack/react-virtual';

function VirtualizedTable({ data, columns }: Props) {
  const tableContainerRef = useRef<HTMLDivElement>(null);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const { rows } = table.getRowModel();

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 48, // estimated row height in px
    overscan: 20,           // render 20 rows above/below viewport
  });

  return (
    <div
      ref={tableContainerRef}
      style={{ height: '600px', overflow: 'auto' }}
    >
      <table>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {/* Spacer for virtual scroll offset */}
          <tr style={{ height: `${virtualizer.getVirtualItems()[0]?.start ?? 0}px` }}>
            <td colSpan={columns.length} />
          </tr>

          {virtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index];
            return (
              <tr key={row.id} ref={virtualizer.measureElement} data-index={virtualRow.index}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}

          {/* Spacer for remaining items */}
          <tr style={{
            height: `${virtualizer.getTotalSize() - (virtualizer.getVirtualItems().at(-1)?.end ?? 0)}px`,
          }}>
            <td colSpan={columns.length} />
          </tr>
        </tbody>
      </table>
    </div>
  );
}
```

### Virtualization Performance Tips

1. **Fixed row height is faster than variable.** If you can make all rows the same height, use `estimateSize: () => 48` and skip `measureElement`.

2. **Overscan wisely.** Too low (< 5) causes visible blank rows on fast scroll. Too high (> 50) defeats the purpose. 20 is a good default.

3. **Memoize cell renderers.** If a cell renderer is expensive, wrap it in `React.memo`.

4. **Do not put forms in virtualized rows.** Scroll will unmount the form, losing state. Use a modal or side panel instead.

---

## TanStack Query Optimization

### Optimal Configuration

```typescript
// query-client.ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,      // 30s — data is fresh for 30s after fetch
      gcTime: 5 * 60_000,     // 5min — unused queries stay in cache for 5min
      retry: 1,               // 1 retry on failure (not 3)
      refetchOnWindowFocus: false, // Disable for data-heavy apps
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 0, // Do not retry mutations
    },
  },
});
```

### Select for Derived Data

```typescript
// BAD: Component receives entire API response, re-renders on any change
const { data } = useQuery({
  queryKey: ['recipients', 'stats', domainId],
  queryFn: () => api.recipients.getStats(domainId),
});
const total = data?.total;
const active = data?.active;

// GOOD: Select extracts only what this component needs
// If the API response changes but total/active do not, this component
// will NOT re-render (referential equality check by TanStack Query).
const { data: stats } = useQuery({
  queryKey: ['recipients', 'stats', domainId],
  queryFn: () => api.recipients.getStats(domainId),
  select: (data) => ({
    total: data.total,
    active: data.active,
  }),
});
```

### Optimistic Updates

```typescript
// For fast-feeling UI on mutations
const updateRecipient = useMutation({
  mutationFn: (updated: UpdateRecipientDto) =>
    api.recipients.update(updated.id, updated),
  onMutate: async (updated) => {
    // Cancel outgoing refetches
    await queryClient.cancelQueries({
      queryKey: ['recipients', 'detail', updated.id],
    });

    // Snapshot previous value
    const previous = queryClient.getQueryData(['recipients', 'detail', updated.id]);

    // Optimistically update the cache
    queryClient.setQueryData(
      ['recipients', 'detail', updated.id],
      (old: Recipient) => ({ ...old, ...updated }),
    );

    return { previous };
  },
  onError: (_err, _updated, context) => {
    // Rollback on error
    queryClient.setQueryData(
      ['recipients', 'detail', context.previous.id],
      context.previous,
    );
  },
  onSettled: (_data, _error, variables) => {
    // Refetch to ensure consistency
    queryClient.invalidateQueries({
      queryKey: ['recipients', 'detail', variables.id],
    });
    queryClient.invalidateQueries({
      queryKey: ['recipients', 'list'],
    });
  },
});
```

### Avoiding Waterfalls

```typescript
// BAD: Sequential fetches — each waits for the previous
function Dashboard({ domainId }: Props) {
  const { data: stats } = useQuery({...}); // fetch 1
  const { data: recent } = useQuery({
    enabled: !!stats, // waits for stats to load
    ...
  }); // fetch 2

  // Total load time = fetch1 + fetch2
}

// GOOD: Parallel fetches
function Dashboard({ domainId }: Props) {
  const { data: stats } = useQuery({
    queryKey: ['recipients', 'stats', domainId],
    queryFn: () => api.recipients.getStats(domainId),
  });
  const { data: recent } = useQuery({
    queryKey: ['recipients', 'recent', domainId],
    queryFn: () => api.recipients.getRecent(domainId),
  });

  // Total load time = max(fetch1, fetch2) — runs in parallel
}

// ALSO GOOD: useSuspenseQueries for guaranteed parallel
const [statsQuery, recentQuery] = useSuspenseQueries({
  queries: [
    {
      queryKey: ['recipients', 'stats', domainId],
      queryFn: () => api.recipients.getStats(domainId),
    },
    {
      queryKey: ['recipients', 'recent', domainId],
      queryFn: () => api.recipients.getRecent(domainId),
    },
  ],
});
```

---

## Image Optimization

### next/image Best Practices

```typescript
// BAD: Raw img tag — no optimization
<img src="/hero.png" alt="Hero" />

// GOOD: next/image with proper sizing
import Image from 'next/image';

<Image
  src="/hero.png"
  alt="Hero"
  width={1200}
  height={630}
  priority           // Above the fold — preload
  quality={85}       // Balanced quality vs size
  placeholder="blur" // Show blur while loading
/>

// For below-the-fold images
<Image
  src="/feature.png"
  alt="Feature"
  width={600}
  height={400}
  loading="lazy"     // Default — only loads when near viewport
  sizes="(max-width: 768px) 100vw, 50vw" // Responsive sizing hints
/>
```

### Avatar and Thumbnail Optimization

```typescript
// For user avatars — serve small, cache aggressively
<Image
  src={user.avatarUrl || '/default-avatar.png'}
  alt={user.name}
  width={40}
  height={40}
  className="rounded-full"
  sizes="40px"       // Always 40px — do not serve larger
/>
```

### Image Format Strategy

| Use Case | Format | Reason |
|----------|--------|--------|
| Photographs | WebP | 25-35% smaller than JPEG |
| Screenshots / UI | WebP or PNG | Lossless for sharp text |
| Icons | SVG | Scales perfectly, tiny file size |
| Animated | WebP or video | Avoid GIF (large, poor quality) |

Next.js automatically serves WebP when the browser supports it (via `Accept` header).

---

## Code Splitting and Lazy Loading

### dynamic() for Heavy Components

```typescript
import dynamic from 'next/dynamic';

// BAD: Importing directly — chart library is in the main bundle
import { LineChart } from '@/components/charts/LineChart';

// GOOD: Dynamic import — chart loads only when needed
const LineChart = dynamic(() => import('@/components/charts/LineChart'), {
  loading: () => <ChartSkeleton />,
  ssr: false, // Charts usually need browser APIs
});

// GOOD: Dynamic import for modals (loaded on user interaction)
const ExportModal = dynamic(() => import('@/components/modals/ExportModal'), {
  loading: () => <ModalSkeleton />,
});

// GOOD: Dynamic import for admin-only features
const AdminPanel = dynamic(() => import('@/components/admin/AdminPanel'), {
  loading: () => <AdminSkeleton />,
});
```

### Route-Based Code Splitting

Next.js automatically code-splits by page/route. Ensure heavy features are on separate routes:

```
app/
  dashboard/        -> loads dashboard-specific code
  recipients/       -> loads table, filters, bulk actions
  campaigns/        -> loads campaign builder, template editor
  analytics/        -> loads charting library (heavy)
  admin/            -> loads admin components (restricted)
```

Each route gets its own JS chunk. Users who never visit `/analytics` never download the charting library.

### Lazy Loading Below-the-Fold Content

```typescript
// For sections below the viewport — load when user scrolls near them
import { useInView } from 'react-intersection-observer';

function DashboardPage() {
  const { ref, inView } = useInView({
    triggerOnce: true,
    rootMargin: '200px', // Start loading 200px before visible
  });

  return (
    <div>
      <DashboardStats />    {/* Above fold — loads immediately */}
      <RecentActivity />    {/* Above fold — loads immediately */}

      <div ref={ref}>
        {inView ? <AnalyticsCharts /> : <ChartSkeleton />}
      </div>
    </div>
  );
}
```

---

## Lighthouse CI Setup

### Installation

```bash
npm install -D @lhci/cli
```

### Configuration

```javascript
// lighthouserc.js
module.exports = {
  ci: {
    collect: {
      url: [
        'http://localhost:3000/',
        'http://localhost:3000/dashboard',
        'http://localhost:3000/recipients',
      ],
      numberOfRuns: 3, // Run 3 times, take median
      startServerCommand: 'npm run start',
      startServerReadyPattern: 'ready on',
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.9 }],
        'first-contentful-paint': ['error', { maxNumericValue: 1500 }],
        'largest-contentful-paint': ['error', { maxNumericValue: 2000 }],
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.1 }],
        'total-blocking-time': ['error', { maxNumericValue: 300 }],
        'max-potential-fid': ['warn', { maxNumericValue: 100 }],
        'resource-summary:script:size': ['error', { maxNumericValue: 500000 }], // 500KB
      },
    },
    upload: {
      target: 'temporary-public-storage', // Free Lighthouse CI storage
    },
  },
};
```

### CI Integration

```yaml
# .github/workflows/lighthouse.yml
name: Lighthouse CI
on:
  pull_request:
    branches: [main]

jobs:
  lighthouse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npm run build
      - run: npx lhci autorun
        env:
          LHCI_GITHUB_APP_TOKEN: ${{ secrets.LHCI_GITHUB_APP_TOKEN }}
```

### Performance Budget Enforcement

```javascript
// budget.json — alternative to Lighthouse CI assertions
[
  {
    "resourceSizes": [
      { "resourceType": "script", "budget": 500 },
      { "resourceType": "stylesheet", "budget": 100 },
      { "resourceType": "image", "budget": 300 },
      { "resourceType": "total", "budget": 1000 }
    ],
    "resourceCounts": [
      { "resourceType": "script", "budget": 20 },
      { "resourceType": "third-party", "budget": 5 }
    ],
    "timings": [
      { "metric": "interactive", "budget": 3000 },
      { "metric": "first-contentful-paint", "budget": 1500 },
      { "metric": "largest-contentful-paint", "budget": 2000 }
    ]
  }
]
```

Add to `next.config.ts`:

```typescript
const nextConfig = {
  experimental: {
    budgets: JSON.parse(fs.readFileSync('./budget.json', 'utf8')),
  },
};
```
