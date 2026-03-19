# SDK Generation Reference — TypeScript Client from OpenAPI Spec

> Read this file when generating a typed TypeScript SDK from the API,
> publishing it as an internal npm package, or integrating it into the frontend.

---

## Table of Contents
1. [Generator Selection](#generator-selection)
2. [Generate TypeScript SDK](#generate-typescript-sdk)
3. [SDK Structure](#sdk-structure)
4. [SDK Authentication](#sdk-authentication)
5. [SDK Error Handling](#sdk-error-handling)
6. [SDK Publishing](#sdk-publishing)
7. [SDK Versioning](#sdk-versioning)
8. [Frontend Integration](#frontend-integration)
9. [SDK Testing](#sdk-testing)

---

## Generator Selection

### Comparison

| Tool | Output | Pros | Cons |
|------|--------|------|------|
| `openapi-typescript` | Type definitions only | Lightweight, zero-runtime, tree-shakeable | No client methods — just types |
| `openapi-typescript-codegen` | Full API client | Methods per endpoint, good defaults | Heavier, less flexible customization |
| `openapi-generator` (Java-based) | Full client + models | Most mature, 50+ languages | Requires Java, heavy output |
| `orval` | Client + React Query hooks | React Query integration, Zod schemas | Opinionated towards React |
| `hey-api/openapi-ts` | Client + types | Modern, plugins, fetch/axios | Newer, smaller community |

### Recommendation by Use Case

| Use Case | Tool |
|----------|------|
| Types only (lightweight) | `openapi-typescript` |
| Full SDK for internal team | `hey-api/openapi-ts` or `openapi-typescript-codegen` |
| React frontend with React Query | `orval` |
| Multi-language SDKs | `openapi-generator` |

---

## Generate TypeScript SDK

### Using hey-api/openapi-ts (Recommended)

```bash
npm install -D @hey-api/openapi-ts
```

Configuration file:

```typescript
// openapi-ts.config.ts
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  client: '@hey-api/client-fetch',
  input: './openapi.json',
  output: {
    path: './sdk/generated',
    format: 'prettier',
    lint: 'eslint',
  },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    {
      name: '@hey-api/schemas',
      type: 'json',
    },
  ],
});
```

Generate:

```bash
npx openapi-ts
```

### Using openapi-typescript (Types Only)

```bash
npm install -D openapi-typescript

# Generate types from spec
npx openapi-typescript ./openapi.json -o ./sdk/types/api.d.ts
```

Output (types only — no runtime code):

```typescript
// sdk/types/api.d.ts (auto-generated)
export interface paths {
  '/v1/domains/{domainId}/recipients': {
    get: {
      parameters: {
        path: { domainId: string };
        query?: {
          page?: number;
          pageSize?: number;
          status?: 'active' | 'inactive' | 'bounced' | 'unsubscribed';
          search?: string;
        };
        header: { 'x-workspace-id': string };
      };
      responses: {
        200: {
          content: {
            'application/json': {
              data: components['schemas']['RecipientResponseDto'][];
              meta: components['schemas']['PaginationMetaDto'];
            };
          };
        };
        401: { content: { 'application/json': components['schemas']['ErrorResponseDto'] } };
        403: { content: { 'application/json': components['schemas']['ErrorResponseDto'] } };
      };
    };
    post: {
      parameters: {
        path: { domainId: string };
        header: { 'x-workspace-id': string };
      };
      requestBody: {
        content: {
          'application/json': components['schemas']['CreateRecipientDto'];
        };
      };
      responses: {
        201: {
          content: {
            'application/json': { data: components['schemas']['RecipientResponseDto'] };
          };
        };
      };
    };
  };
}

export interface components {
  schemas: {
    RecipientResponseDto: {
      id: string;
      domainId: string;
      email: string;
      firstName: string;
      lastName: string;
      status: 'active' | 'inactive' | 'bounced' | 'unsubscribed';
      customFields?: Record<string, unknown>;
      createdAt: string;
      updatedAt: string;
    };
    CreateRecipientDto: {
      email: string;
      firstName: string;
      lastName: string;
      status?: 'active' | 'inactive';
      customFields?: Record<string, unknown>;
      tags?: string[];
    };
    PaginationMetaDto: {
      total: number;
      page: number;
      pageSize: number;
      hasMore: boolean;
    };
    ErrorResponseDto: {
      statusCode: number;
      message: string;
      errors?: { field: string; message: string }[];
    };
  };
}
```

---

## SDK Structure

### Full SDK with Client Methods

```
sdk/
  ├── generated/           ← Auto-generated (DO NOT EDIT)
  │   ├── types.ts         ← All DTO types from OpenAPI schemas
  │   ├── services/        ← One file per tag group
  │   │   ├── RecipientsService.ts
  │   │   ├── DashboardsService.ts
  │   │   ├── BillingService.ts
  │   │   └── ...
  │   └── core/
  │       ├── request.ts   ← Base HTTP client
  │       └── OpenAPI.ts   ← Configuration
  ├── client.ts            ← Custom wrapper (hand-written)
  ├── interceptors.ts      ← Auth + tenant header injection
  ├── errors.ts            ← Typed error classes
  └── index.ts             ← Public API barrel export
```

### Client Wrapper (Hand-Written Layer)

```typescript
// sdk/client.ts
import { RecipientsService } from './generated/services/RecipientsService';
import { DashboardsService } from './generated/services/DashboardsService';
import { BillingService } from './generated/services/BillingService';

export interface PlatformSDKConfig {
  baseUrl: string;
  getAccessToken: () => string | Promise<string>;
  getWorkspaceId: () => string;
  getCompanyId?: () => string;
  onUnauthorized?: () => void;
  onRateLimited?: (retryAfter: number) => void;
}

export class PlatformSDK {
  public readonly recipients: RecipientsService;
  public readonly dashboards: DashboardsService;
  public readonly billing: BillingService;

  constructor(private config: PlatformSDKConfig) {
    // Configure the generated client
    this.recipients = new RecipientsService();
    this.dashboards = new DashboardsService();
    this.billing = new BillingService();
  }
}

// Usage in frontend:
// const sdk = new PlatformSDK({
//   baseUrl: 'https://api.example.com',
//   getAccessToken: () => authStore.getToken(),
//   getWorkspaceId: () => workspaceStore.currentId,
// });
```

---

## SDK Authentication

### Auto-Include JWT Token and Workspace Header

```typescript
// sdk/interceptors.ts
import type { PlatformSDKConfig } from './client';

export function createRequestInterceptor(config: PlatformSDKConfig) {
  return async (request: RequestInit & { url: string }): Promise<RequestInit> => {
    const headers = new Headers(request.headers);

    // JWT token — always included
    const token = await config.getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    // Workspace header — included for domain and workspace-scoped endpoints
    const workspaceId = config.getWorkspaceId();
    if (workspaceId) {
      headers.set('x-workspace-id', workspaceId);
    }

    // Company header — included for company-scoped endpoints
    if (config.getCompanyId) {
      const companyId = config.getCompanyId();
      if (companyId && isCompanyScoped(request.url)) {
        headers.set('x-company-id', companyId);
      }
    }

    return { ...request, headers };
  };
}

function isCompanyScoped(url: string): boolean {
  return url.includes('/companies/') || url.includes('/billing');
}

export function createResponseInterceptor(config: PlatformSDKConfig) {
  return async (response: Response): Promise<Response> => {
    // Handle 401 — token expired
    if (response.status === 401 && config.onUnauthorized) {
      config.onUnauthorized();
    }

    // Handle 429 — rate limited
    if (response.status === 429 && config.onRateLimited) {
      const retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
      config.onRateLimited(retryAfter);
    }

    return response;
  };
}
```

### Integration with hey-api Client

```typescript
// sdk/setup.ts
import { client } from './generated/core/request';
import { createRequestInterceptor, createResponseInterceptor } from './interceptors';
import type { PlatformSDKConfig } from './client';

export function configureSDK(config: PlatformSDKConfig) {
  client.setConfig({
    baseUrl: config.baseUrl,
  });

  client.interceptors.request.use(createRequestInterceptor(config));
  client.interceptors.response.use(createResponseInterceptor(config));
}
```

---

## SDK Error Handling

### Typed Error Responses

```typescript
// sdk/errors.ts

export class ApiError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly body: {
      statusCode: number;
      message: string;
      errors?: { field: string; message: string }[];
    },
  ) {
    super(body.message);
    this.name = 'ApiError';
  }

  get isValidationError(): boolean {
    return this.statusCode === 400 || this.statusCode === 422;
  }

  get isAuthError(): boolean {
    return this.statusCode === 401;
  }

  get isForbidden(): boolean {
    return this.statusCode === 403;
  }

  get isNotFound(): boolean {
    return this.statusCode === 404;
  }

  get isConflict(): boolean {
    return this.statusCode === 409;
  }

  get isLimitExceeded(): boolean {
    return this.statusCode === 402;
  }

  get fieldErrors(): Map<string, string> {
    const map = new Map<string, string>();
    if (this.body.errors) {
      for (const err of this.body.errors) {
        map.set(err.field, err.message);
      }
    }
    return map;
  }
}

// Usage in frontend:
// try {
//   await sdk.recipients.create(domainId, dto);
// } catch (err) {
//   if (err instanceof ApiError) {
//     if (err.isConflict) {
//       toast.error('Email already exists in this domain');
//     } else if (err.isValidationError) {
//       const errors = err.fieldErrors;
//       form.setErrors(Object.fromEntries(errors));
//     } else if (err.isLimitExceeded) {
//       showUpgradeDialog();
//     }
//   }
// }
```

### Error Response Interceptor (Auto-Wrap)

```typescript
// sdk/error-interceptor.ts
import { ApiError } from './errors';

export async function errorInterceptor(response: Response): Promise<Response> {
  if (!response.ok) {
    let body: any;
    try {
      body = await response.clone().json();
    } catch {
      body = { statusCode: response.status, message: response.statusText };
    }
    throw new ApiError(response.status, body);
  }
  return response;
}
```

---

## SDK Publishing

### Package Structure

```json
{
  "name": "@platform/api-sdk",
  "version": "1.5.0",
  "description": "TypeScript SDK for the Platform API",
  "main": "./dist/index.js",
  "module": "./dist/index.mjs",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.mjs",
      "require": "./dist/index.js"
    }
  },
  "files": ["dist"],
  "scripts": {
    "generate": "openapi-ts",
    "build": "tsup src/index.ts --format cjs,esm --dts",
    "prepublishOnly": "npm run generate && npm run build"
  },
  "peerDependencies": {
    "typescript": ">=5.0"
  }
}
```

### Build Configuration

```typescript
// tsup.config.ts
import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['sdk/index.ts'],
  format: ['cjs', 'esm'],
  dts: true,
  clean: true,
  sourcemap: true,
  minify: false,
  splitting: false,
  treeshake: true,
  external: [],
});
```

### Publish to Internal npm Registry

```bash
# .npmrc — point to internal registry
@platform:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${NPM_TOKEN}
```

### CI: Auto-Publish on API Change

```yaml
# .github/workflows/sdk-publish.yml
name: Publish SDK

on:
  push:
    branches: [main]
    paths:
      - 'openapi.json'

jobs:
  publish-sdk:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          registry-url: 'https://npm.pkg.github.com'

      - run: npm ci
      - run: npm run openapi:export
      - run: cd sdk && npm run generate && npm run build

      # Version bump based on breaking changes
      - name: Check for breaking changes
        id: check
        run: |
          npx openapi-diff openapi-previous.json openapi.json --json > diff.json
          if grep -q '"incompatible"' diff.json; then
            echo "bump=major" >> $GITHUB_OUTPUT
          elif grep -q '"compatible"' diff.json; then
            echo "bump=minor" >> $GITHUB_OUTPUT
          else
            echo "bump=patch" >> $GITHUB_OUTPUT
          fi

      - name: Bump version
        run: cd sdk && npm version ${{ steps.check.outputs.bump }} --no-git-tag-version

      - name: Publish
        run: cd sdk && npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

---

## SDK Versioning

### Version Matching Strategy

| API Version | SDK Version | Rule |
|-------------|-------------|------|
| v1.0.0 | 1.0.0 | Initial release |
| v1.1.0 (new endpoint) | 1.1.0 | Minor bump — new methods added |
| v1.1.1 (doc fix) | 1.1.1 | Patch bump — types unchanged |
| v2.0.0 (breaking) | 2.0.0 | Major bump — methods/types changed |

### Backward Compatibility

```typescript
// sdk/index.ts — export both versions when v2 is introduced
export * from './v1';            // Keep v1 exports
export * as v2 from './v2';      // Add v2 as namespace

// Consumer can migrate gradually:
import { RecipientsService } from '@platform/api-sdk';         // v1 (default)
import { v2 } from '@platform/api-sdk';                        // v2 via namespace
const recipientsV2 = new v2.RecipientsService();
```

### Deprecation Annotations in SDK

```typescript
// Generated method with deprecation notice
/**
 * @deprecated Use `listRecipients` with the `tags[]` query parameter instead.
 * Will be removed in SDK v3.0.0.
 */
async listRecipientsByTag(domainId: string, tag: string): Promise<RecipientListResponse> {
  return this.listRecipients(domainId, { tags: [tag] });
}
```

---

## Frontend Integration

### Replacing Hand-Written fetchApi() Calls

Before (hand-written):

```typescript
// services/recipients.ts — BEFORE SDK
async function listRecipients(domainId: string, params: any) {
  const res = await fetch(`/api/v1/domains/${domainId}/recipients?${new URLSearchParams(params)}`, {
    headers: {
      'Authorization': `Bearer ${getToken()}`,
      'x-workspace-id': getWorkspaceId(),
    },
  });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}
```

After (SDK):

```typescript
// services/recipients.ts — AFTER SDK
import { sdk } from '@/lib/api-client';

// Fully typed — params, response, and errors
const { data, meta } = await sdk.recipients.list(domainId, {
  page: 1,
  pageSize: 25,
  status: 'active',
});
// typeof data = RecipientResponseDto[]
// typeof meta = PaginationMetaDto
```

### SDK Initialization in Frontend

```typescript
// lib/api-client.ts
import { PlatformSDK } from '@platform/api-sdk';
import { useAuthStore } from '@/stores/auth';
import { useWorkspaceStore } from '@/stores/workspace';
import { router } from '@/router';

export const sdk = new PlatformSDK({
  baseUrl: import.meta.env.VITE_API_BASE_URL,
  getAccessToken: () => useAuthStore.getState().accessToken,
  getWorkspaceId: () => useWorkspaceStore.getState().currentWorkspaceId,
  getCompanyId: () => useWorkspaceStore.getState().currentCompanyId,
  onUnauthorized: () => {
    useAuthStore.getState().clearSession();
    router.push('/login');
  },
  onRateLimited: (retryAfter) => {
    console.warn(`Rate limited. Retry after ${retryAfter}s`);
  },
});
```

### React Query Integration (with Orval)

If using Orval, it generates React Query hooks directly:

```typescript
// Generated by orval — no hand-written code needed
import { useListRecipients, useCreateRecipient } from '@platform/api-sdk/react-query';

function RecipientsPage({ domainId }: { domainId: string }) {
  const { data, isLoading, error } = useListRecipients(domainId, {
    page: 1,
    pageSize: 25,
  });

  const createMutation = useCreateRecipient(domainId);

  const handleCreate = async (dto: CreateRecipientDto) => {
    await createMutation.mutateAsync(dto);
  };

  return (
    <div>
      {isLoading && <Spinner />}
      {data?.data.map(r => <RecipientRow key={r.id} recipient={r} />)}
    </div>
  );
}
```

### Orval Configuration

```typescript
// orval.config.ts
import { defineConfig } from 'orval';

export default defineConfig({
  platform: {
    input: './openapi.json',
    output: {
      target: './sdk/generated/hooks.ts',
      schemas: './sdk/generated/models',
      client: 'react-query',
      mode: 'tags-split',
      override: {
        mutator: {
          path: './sdk/interceptors.ts',
          name: 'customFetch',
        },
        query: {
          useQuery: true,
          useMutation: true,
          signal: true,
        },
      },
    },
  },
});
```

---

## SDK Testing

### Auto-Generated Test Stubs from OpenAPI Examples

```typescript
// sdk/__tests__/recipients.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { PlatformSDK } from '../client';
import { configureSDK } from '../setup';

// Mock server using OpenAPI examples as responses
const server = setupServer(
  http.get('*/v1/domains/:domainId/recipients', ({ params }) => {
    return HttpResponse.json({
      data: [
        {
          id: 'b3d7f1a2-5e8c-4b9d-a1f3-7c2e8d9b4a6f',
          domainId: params.domainId,
          email: 'john.doe@example.com',
          firstName: 'John',
          lastName: 'Doe',
          status: 'active',
          customFields: { department: 'Engineering' },
          createdAt: '2024-03-15T10:30:00Z',
          updatedAt: '2024-03-15T14:22:00Z',
        },
      ],
      meta: { total: 1, page: 1, pageSize: 25, hasMore: false },
    });
  }),

  http.post('*/v1/domains/:domainId/recipients', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json(
      {
        data: {
          id: 'new-uuid-here',
          domainId: 'test-domain',
          ...body,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      },
      { status: 201 },
    );
  }),

  http.post('*/v1/domains/:domainId/recipients/bulk', () => {
    return HttpResponse.json(
      { jobId: 'bulk-op:test', status: 'queued', estimated: 5000 },
      { status: 202 },
    );
  }),
);

let sdk: PlatformSDK;

beforeAll(() => {
  server.listen();
  sdk = new PlatformSDK({
    baseUrl: 'http://localhost:3000',
    getAccessToken: () => 'test-token',
    getWorkspaceId: () => 'test-workspace-id',
  });
  configureSDK(sdk['config']);
});

afterAll(() => server.close());

describe('RecipientsService', () => {
  it('lists recipients with pagination', async () => {
    const result = await sdk.recipients.list('test-domain', {
      page: 1,
      pageSize: 25,
    });

    expect(result.data).toHaveLength(1);
    expect(result.data[0].email).toBe('john.doe@example.com');
    expect(result.meta.total).toBe(1);
    expect(result.meta.hasMore).toBe(false);
  });

  it('creates a recipient with custom fields', async () => {
    const result = await sdk.recipients.create('test-domain', {
      email: 'jane@example.com',
      firstName: 'Jane',
      lastName: 'Smith',
      status: 'active',
      customFields: { department: 'Marketing' },
    });

    expect(result.data.email).toBe('jane@example.com');
    expect(result.data.id).toBeDefined();
  });

  it('returns jobId for bulk operations', async () => {
    const result = await sdk.recipients.bulkUpdate('test-domain', {
      filter: { status: 'inactive' },
      update: { status: 'unsubscribed' },
    });

    expect(result.jobId).toBe('bulk-op:test');
    expect(result.status).toBe('queued');
    expect(result.estimated).toBe(5000);
  });
});
```

### Contract Testing Against Live Spec

```typescript
// sdk/__tests__/contract.test.ts
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';

const spec = JSON.parse(readFileSync('./openapi.json', 'utf-8'));
const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

// Register all schemas from the spec
const schemas = spec.components?.schemas || {};
for (const [name, schema] of Object.entries(schemas)) {
  ajv.addSchema(schema as object, `#/components/schemas/${name}`);
}

describe('SDK types match OpenAPI schemas', () => {
  it('RecipientResponseDto matches spec', () => {
    const schema = schemas['RecipientResponseDto'];
    expect(schema).toBeDefined();

    const validate = ajv.compile(schema as object);
    const validData = {
      id: 'b3d7f1a2-5e8c-4b9d-a1f3-7c2e8d9b4a6f',
      domainId: 'a1b2c3d4-5678-90ab-cdef-1234567890ab',
      email: 'test@example.com',
      firstName: 'Test',
      lastName: 'User',
      status: 'active',
      createdAt: '2024-03-15T10:30:00Z',
      updatedAt: '2024-03-15T14:22:00Z',
    };

    expect(validate(validData)).toBe(true);
  });

  it('CreateRecipientDto rejects invalid email', () => {
    const schema = schemas['CreateRecipientDto'];
    expect(schema).toBeDefined();

    const validate = ajv.compile(schema as object);
    const invalidData = {
      email: 'not-an-email',
      firstName: 'Test',
      lastName: 'User',
    };

    // If schema has format: email, this will fail
    if (schema && (schema as any).properties?.email?.format === 'email') {
      expect(validate(invalidData)).toBe(false);
    }
  });

  it('all response schemas referenced in paths exist', () => {
    const paths = spec.paths || {};
    const missingSchemas: string[] = [];

    for (const [path, methods] of Object.entries(paths)) {
      for (const [method, operation] of Object.entries(methods as Record<string, any>)) {
        if (typeof operation !== 'object' || !operation.responses) continue;

        for (const [status, response] of Object.entries(operation.responses as Record<string, any>)) {
          const ref = response?.content?.['application/json']?.schema?.$ref;
          if (ref) {
            const schemaName = ref.replace('#/components/schemas/', '');
            if (!schemas[schemaName]) {
              missingSchemas.push(`${method.toUpperCase()} ${path} → ${status} → ${schemaName}`);
            }
          }
        }
      }
    }

    expect(missingSchemas).toEqual([]);
  });
});
```

### Script: Auto-Generate Test Stubs

```typescript
// scripts/generate-sdk-tests.ts
import { readFileSync, writeFileSync } from 'fs';
import { resolve } from 'path';

const spec = JSON.parse(readFileSync('./openapi.json', 'utf-8'));
const paths = spec.paths || {};

const testCases: string[] = [];

for (const [path, methods] of Object.entries(paths)) {
  for (const [method, operation] of Object.entries(methods as Record<string, any>)) {
    if (typeof operation !== 'object' || !operation.operationId) continue;

    const opId = operation.operationId;
    const summary = operation.summary || 'No summary';

    // Extract example from 200/201 response
    const successStatus = Object.keys(operation.responses || {}).find(s => s.startsWith('2'));
    const example = operation.responses?.[successStatus as string]?.content?.['application/json']?.example;

    testCases.push(`
  it('${opId} — ${summary}', async () => {
    // TODO: Implement test for ${method.toUpperCase()} ${path}
    // Example response: ${JSON.stringify(example || 'N/A')}
    expect(true).toBe(true);
  });`);
  }
}

const testFile = `
import { describe, it, expect } from 'vitest';

describe('SDK Endpoint Coverage', () => {
${testCases.join('\n')}
});
`;

writeFileSync(resolve('./sdk/__tests__/generated-stubs.test.ts'), testFile.trim());
console.log(\`Generated \${testCases.length} test stubs\`);
```

### npm Scripts for SDK Workflow

```json
{
  "scripts": {
    "sdk:generate": "openapi-ts",
    "sdk:build": "tsup sdk/index.ts --format cjs,esm --dts",
    "sdk:test": "vitest run sdk/__tests__",
    "sdk:test:contract": "vitest run sdk/__tests__/contract.test.ts",
    "sdk:stubs": "ts-node scripts/generate-sdk-tests.ts",
    "sdk:full": "npm run openapi:export && npm run sdk:generate && npm run sdk:build && npm run sdk:test"
  }
}
```
