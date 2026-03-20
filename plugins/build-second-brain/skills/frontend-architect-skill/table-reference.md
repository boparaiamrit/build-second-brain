# UnifiedDataTable Reference

The UnifiedDataTable is the **foundation component** for ALL list views. Never build a custom table from scratch.

## Architecture

```
unified-data-table/
├── unified-data-table.tsx      # Main component (893 lines)
├── types.ts                    # Props & config interfaces
├── use-table-persistence.ts    # localStorage persistence hook
├── sortable-column-item.tsx    # Column visibility/reorder in menu
├── sortable-filter-item.tsx    # Filter visibility/reorder in menu
└── sortable-table-head.tsx     # Draggable table headers
```

## Key Features

| Feature | How It Works |
|---------|-------------|
| **Column Persistence** | localStorage: visibility, order, sizing per `localStoragePrefix` |
| **Column Reorder** | @dnd-kit horizontal drag on headers + vertical in menu |
| **Column Pinning** | `columnDefaults.pinned.left/right` — always select left, actions right |
| **Column Resize** | Drag divider on header. Double-click to reset. `columnResizeMode: "onChange"` |
| **Row Selection** | Controlled (`externalRowSelection`) or uncontrolled (internal). Gmail-style select-all-across-pages. |
| **Global Search** | `enableSearch` + `globalFilterFn` — searches across all columns |
| **Column Filters** | Multi-select pill chips. `filters` prop with `ColumnFilterConfig[]` |
| **Advanced Search** | Render props: `advancedSearch.renderDialog` — pre-filters data before table |
| **Bulk Actions** | `bulkActions` with confirmation dialogs. Or `renderBulkActions` for custom UI |
| **Empty States** | `replace` mode (entire table replaced) or `inline` mode (in table body) |
| **Pagination** | Client-side. `defaultPageSize`, `pageSizeOptions` |
| **Sorting** | Multi-column sorting. Persisted to localStorage |

## Three-Layer Filter Hierarchy

```
Layer 1: Global Search (globalFilterFn — fast text search)
Layer 2: Column Filters (multi-select pills — faceted filtering)
Layer 3: Advanced Search (custom dialog — complex AND/OR conditions)
```

All three layers compose — they don't replace each other.

## Props Quick Reference

```typescript
// Required
columns: ColumnDef<TData, TValue>[]
data: TData[]
localStoragePrefix: string

// Common
enableSearch?: boolean
enableRowSelection?: boolean
filters?: ColumnFilterConfig[]
bulkActions?: BulkActionConfig<TData>[]
columnDefaults?: { pinned?: { left: string[], right: string[] }, visibility?: Record<string, boolean> }
defaultPageSize?: number
defaultSorting?: SortingState
tableMeta?: Record<string, any>  // Passed to column cells
emptyState?: { mode: 'replace' | 'inline', icon, title, description, actions? }

// Advanced
advancedSearch?: { renderTrigger, renderDialog, applySearch, emptyState }
renderBulkActions?: (table, selectedItems, clearSelection) => ReactNode
renderToolbarLeft/Center/Right?: (table) => ReactNode
sanitizePersistedState?: (state) => state  // Handle schema migrations
```

## Column Definition Patterns

### Selection Column (ALWAYS first, pinned left)
```typescript
{ id: 'select', size: 40, enableHiding: false, enableResizing: false,
  header: SelectAllCheckbox, cell: SelectRowCheckbox }
```

### Sortable Text Column
```typescript
{ accessorKey: 'email',
  header: ({ column }) => <SortButton column={column}>Email</SortButton>,
  cell: ({ row }) => row.original.email }
```

### Editable Cell Column
```typescript
{ accessorKey: 'department',
  cell: ({ row, table }) => <EditableCell value={row.original.department}
    onSave={(val) => table.options.meta?.onUpdateField(row.original.id, 'department', val)} /> }
```

### Multi-Select Filter Column
```typescript
{ accessorKey: 'status',
  filterFn: (row, id, values: string[]) => !values?.length || values.includes(row.getValue(id)) }
```

### Actions Column (ALWAYS last, pinned right)
```typescript
{ id: 'actions', size: 60, enableHiding: false,
  cell: ({ row }) => <ActionsDropdown item={row.original} /> }
```

## localStorage Keys (per prefix)

```
{prefix}-column-visibility
{prefix}-column-order
{prefix}-column-sizing
{prefix}-filter-visibility
{prefix}-filter-order
{prefix}-sorting
{prefix}-global-filter
{prefix}-column-filters
{prefix}-row-selection
{prefix}-advanced-search
```
