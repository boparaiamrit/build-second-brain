# Wizard & Import Reference

Reference implementation from the CSV import wizard — the quality bar for all multi-step workflows.

## Wizard Architecture

```
{feature}-wizard.tsx           # Container: state + step routing
steps/
  step-upload.tsx              # Step 1: File/data input
  step-configure.tsx           # Step 2: Mapping/config
  step-review.tsx              # Step 3: Preview + confirm + execute
utils/
  auto-mapper.ts               # Complex matching logic
  duplicate-analyzer.ts        # Dedup detection
  chunked-processor.ts         # UI-safe batch processing
  group-extractor.ts           # Data extraction utilities
```

## Wizard State Pattern

**Single source of truth — ONE state object shared across all steps:**

```typescript
interface WizardState {
  // Step tracking
  step: 1 | 2 | 3

  // Step 1: Input data
  file: File | null
  fileName: string
  parsedData: Record<string, string>[]
  csvHeaders: string[]

  // Step 2: Configuration
  fieldMappings: FieldMapping[]
  duplicateHandling: 'skip' | 'update' | 'skip_export'
  duplicateDetectionFields: string[]
  selectedGroups: string[]
  tags: string[]

  // Step 2: Analysis results
  duplicateAnalysis: DuplicateAnalysisResult | null
  isAnalyzing: boolean

  // Step 3: Execution
  isImporting: boolean
  importProgress: number
  deletedRowIndices: number[]
}
```

**Rules:**
- State is a SINGLE object (not 10 separate useState calls)
- All steps receive `state` + `updateState` as props
- `updateState` merges partial updates: `setState(prev => ({ ...prev, ...partial }))`
- State persists across step navigation (going back doesn't lose data)

## Auto-Mapper (82KB reference implementation)

**Seven scoring strategies with weighted composite:**

```typescript
const WEIGHTS = {
  exactRaw: 0.25,           // Case-insensitive exact match
  exactNormalized: 0.20,    // Match after normalization (remove special chars)
  tokenOverlap: 0.20,       // Jaccard similarity on word tokens
  prefixSuffix: 0.08,       // Substring containment
  abbreviation: 0.10,       // "dept" → "department", "fname" → "firstName"
  levenshtein: 0.07,        // Edit distance for typos
  valueType: 0.10,          // Sample value type inference (email, phone, date)
}

const AUTO_MAP_THRESHOLD = 40  // Minimum confidence to auto-map
```

**Pipeline:**
1. Build field targets (static fields + custom fields)
2. Pre-compute header metadata (normalized, tokenized)
3. Score all (header, target) pairs using 7 strategies
4. Greedy optimal assignment (prevent duplicate assignments)

## Duplicate Analyzer (Multi-Field)

**Composite key strategy:**

```typescript
// Create key from multiple fields
function createCompositeKey(row, fields, fieldColumnMap): string {
  const values = fields.map(f => normalizeValue(row[fieldColumnMap[f]]))
  if (values.some(v => !v)) return ''  // Incomplete key = new
  return values.join('|')  // 'john@example.com|555-1234|EMP001'
}
```

**Detection flow:**
1. Build lookup set from existing records
2. For each CSV row: create composite key → check against existing + already-seen-in-CSV
3. Classify: new / duplicate / invalid
4. Process in chunks (1000 rows per chunk) to prevent UI freeze

## Chunked Processor

**MANDATORY for >1000 items:**

```typescript
async function processInChunks<T, R>(config: {
  data: T[]
  chunkSize: number  // 1000 default
  processor: (chunk: T[], startIndex: number) => R[]
  onProgress: (percent: number) => void
}): Promise<R[]> {
  for (let i = 0; i < data.length; i += chunkSize) {
    const chunk = data.slice(i, i + chunkSize)
    results.push(...processor(chunk, i))
    onProgress(Math.round(((i + chunk.length) / data.length) * 100))
    await new Promise(resolve => setTimeout(resolve, 0))  // YIELD TO UI THREAD
  }
  return results
}
```

**The `setTimeout(0)` is critical** — it yields control back to React so the UI can re-render progress updates. Without it, the browser freezes during processing.

## Import Execution Pattern

```typescript
// Chunk the import into batches of 100
const chunkSize = 100
for (let i = 0; i < recipients.length; i += chunkSize) {
  const chunk = recipients.slice(i, i + chunkSize)
  await fetch('/api/recipients/import', {
    method: 'POST',
    body: JSON.stringify({ recipients: chunk, duplicateHandling }),
  })
  updateState({ importProgress: Math.round((i + chunk.length) / recipients.length * 100) })
}
```

## Quality Standards (from reference implementation)

- Auto-mapper uses 7 strategies with composite scoring
- Duplicate detection supports multiple fields (not just email)
- Editable review table lets users fix/delete rows before import
- Department normalization suggestions
- Export skipped rows as CSV/Excel
- Full import history tracking
- Snapshot support for undo capability
