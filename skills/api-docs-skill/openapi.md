# OpenAPI Reference — Full Swagger Setup, Theming, CI, and Export

> Read this file when configuring the Swagger module, customizing the UI,
> validating specs in CI, or exporting to Postman/Redoc.

---

## Table of Contents
1. [Full NestJS Swagger Module Setup](#full-nestjs-swagger-module-setup)
2. [Custom Swagger UI Theme](#custom-swagger-ui-theme)
3. [Grouping Endpoints by Module and Scope](#grouping-endpoints)
4. [Authentication in Swagger UI](#authentication-in-swagger-ui)
5. [Example Values Reference](#example-values-reference)
6. [Multi-Tenant Headers as Global Parameters](#multi-tenant-headers)
7. [Export OpenAPI Spec as JSON/YAML](#export-openapi-spec)
8. [OpenAPI Spec Validation in CI](#openapi-validation-in-ci)
9. [Postman Collection Generation](#postman-collection-generation)
10. [Redoc for Public-Facing Docs](#redoc-for-public-facing-docs)

---

## Full NestJS Swagger Module Setup

### Dependencies

```bash
npm install @nestjs/swagger swagger-ui-express
# For YAML export:
npm install yaml
# For Redoc:
npm install nestjs-redoc
```

### Complete Bootstrap Configuration

```typescript
// main.ts
import { NestFactory } from '@nestjs/core';
import { VersioningType, ValidationPipe } from '@nestjs/common';
import { SwaggerModule, DocumentBuilder } from '@nestjs/swagger';
import { writeFileSync } from 'fs';
import { dump } from 'yaml';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // Enable API versioning
  app.enableVersioning({
    type: VersioningType.URI,
    defaultVersion: '1',
    prefix: 'v',
  });

  // Global validation pipe
  app.useGlobalPipes(new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
    transform: true,
  }));

  // Swagger configuration
  const config = new DocumentBuilder()
    .setTitle('Platform API')
    .setDescription(
      '## Multi-Tenant SaaS API\n\n'
      + 'This API uses a Company → Workspace → Domain hierarchy.\n\n'
      + '### Authentication\n'
      + 'All endpoints require a valid JWT token in the `Authorization` header.\n\n'
      + '### Tenant Context\n'
      + '- **Domain-scoped** endpoints: require `domainId` in the path\n'
      + '- **Workspace-scoped** endpoints: require `x-workspace-id` header\n'
      + '- **Company-scoped** endpoints: require `x-company-id` header\n\n'
      + '### Response Format\n'
      + '- Single entity: `{ data: T }`\n'
      + '- List: `{ data: T[], meta: { total, page, pageSize, hasMore } }`\n'
      + '- Async job: `{ jobId, status, estimated? }`\n'
      + '- Error: `{ statusCode, message, errors? }`\n',
    )
    .setVersion('1.0')
    .setContact('API Team', 'https://docs.example.com', 'api@example.com')
    .setLicense('Proprietary', 'https://example.com/license')
    .setExternalDoc('Full Developer Guide', 'https://docs.example.com/guide')

    // Authentication schemes
    .addBearerAuth(
      {
        type: 'http',
        scheme: 'bearer',
        bearerFormat: 'JWT',
        description: 'Enter your JWT access token',
      },
      'access-token',
    )
    .addApiKey(
      {
        type: 'apiKey',
        name: 'x-workspace-id',
        in: 'header',
        description: 'Workspace UUID — required for workspace-scoped and domain-scoped endpoints',
      },
      'workspace-id',
    )
    .addApiKey(
      {
        type: 'apiKey',
        name: 'x-company-id',
        in: 'header',
        description: 'Company UUID — required for company-scoped endpoints (billing, admin)',
      },
      'company-id',
    )

    // Server environments
    .addServer('http://localhost:3000', 'Local Development')
    .addServer('https://api.staging.example.com', 'Staging')
    .addServer('https://api.example.com', 'Production')

    // Tag groups — ordered by scope
    .addTag('Public — Auth', 'Authentication and token management')
    .addTag('Public — Health', 'Health checks and service status')
    .addTag('Domain — Recipients', 'Recipient CRUD scoped to a domain')
    .addTag('Domain — Campaigns', 'Campaign management within a domain')
    .addTag('Domain — Events', 'Event tracking within a domain')
    .addTag('Domain — Import', 'File import and staging within a domain')
    .addTag('Workspace — Dashboards', 'Cross-domain reporting and analytics')
    .addTag('Workspace — Settings', 'Workspace-level configuration and custom fields')
    .addTag('Workspace — Users', 'User and role management within a workspace')
    .addTag('Company — Billing', 'Subscription, usage, and invoicing')
    .addTag('Company — Admin', 'Company-wide administration')
    .addTag('Company — Blueprints', 'Cross-workspace deployment templates')
    .build();

  const document = SwaggerModule.createDocument(app, config, {
    operationIdFactory: (controllerKey: string, methodKey: string) =>
      `${controllerKey}_${methodKey}`,
    extraModels: [
      // Register shared DTOs so they appear in schemas
      PaginationMetaDto,
      ErrorResponseDto,
    ],
  });

  // Export spec to file for CI and SDK generation
  if (process.env.EXPORT_OPENAPI === 'true') {
    writeFileSync('./openapi.json', JSON.stringify(document, null, 2));
    writeFileSync('./openapi.yaml', dump(document));
    console.log('OpenAPI spec exported to openapi.json and openapi.yaml');
  }

  // Mount Swagger UI
  SwaggerModule.setup('api/docs', app, document, {
    customSiteTitle: 'Platform API Docs',
    customfavIcon: '/assets/favicon.ico',
    customCssUrl: '/assets/swagger-theme.css',
    swaggerOptions: {
      persistAuthorization: true,
      tagsSorter: 'alpha',
      operationsSorter: 'alpha',
      docExpansion: 'none',
      filter: true,
      showRequestDuration: true,
      defaultModelsExpandDepth: 3,
      defaultModelExpandDepth: 3,
      tryItOutEnabled: true,
    },
  });

  await app.listen(3000);
}
bootstrap();
```

---

## Custom Swagger UI Theme

### CSS Override for Product Branding

```css
/* public/assets/swagger-theme.css */

/* Top bar */
.swagger-ui .topbar {
  background-color: #1a1a2e;
  padding: 10px 0;
}

.swagger-ui .topbar .download-url-wrapper {
  display: none;
}

/* Info section */
.swagger-ui .info .title {
  color: #1a1a2e;
  font-family: 'Inter', -apple-system, sans-serif;
}

.swagger-ui .info .description p {
  font-size: 14px;
  line-height: 1.6;
}

/* Tag headers */
.swagger-ui .opblock-tag {
  font-family: 'Inter', -apple-system, sans-serif;
  border-bottom: 2px solid #e0e0e0;
}

/* HTTP method badges */
.swagger-ui .opblock.opblock-get .opblock-summary-method {
  background: #2563eb;
}

.swagger-ui .opblock.opblock-post .opblock-summary-method {
  background: #16a34a;
}

.swagger-ui .opblock.opblock-patch .opblock-summary-method {
  background: #d97706;
}

.swagger-ui .opblock.opblock-delete .opblock-summary-method {
  background: #dc2626;
}

/* Deprecated endpoint styling */
.swagger-ui .opblock.opblock-deprecated {
  opacity: 0.6;
  border-color: #9ca3af;
}

.swagger-ui .opblock.opblock-deprecated .opblock-summary-method {
  background: #6b7280;
}

/* Authorization button */
.swagger-ui .btn.authorize {
  color: #2563eb;
  border-color: #2563eb;
}

.swagger-ui .btn.authorize svg {
  fill: #2563eb;
}

/* Schema section */
.swagger-ui .model-title {
  font-family: 'Inter', -apple-system, sans-serif;
}

/* Try it out button */
.swagger-ui .btn.try-out__btn {
  color: #2563eb;
  border-color: #2563eb;
}

.swagger-ui .btn.execute {
  background-color: #2563eb;
  border-color: #2563eb;
}
```

---

## Grouping Endpoints

### By Module AND by Tenant Scope

Use a naming convention in `@ApiTags()` to achieve dual grouping:

```typescript
// Convention: "Scope — Module"
// This makes Swagger UI group by scope first, then alphabetically by module

// Domain-scoped endpoints
@ApiTags('Domain — Recipients')
@Controller('domains/:domainId/recipients')
export class RecipientsController {}

@ApiTags('Domain — Campaigns')
@Controller('domains/:domainId/campaigns')
export class CampaignsController {}

// Workspace-scoped endpoints
@ApiTags('Workspace — Dashboards')
@Controller('workspaces/:workspaceId/dashboards')
export class DashboardsController {}

@ApiTags('Workspace — Settings')
@Controller('workspaces/:workspaceId/settings')
export class SettingsController {}

// Company-scoped endpoints
@ApiTags('Company — Billing')
@Controller('companies/:companyId/billing')
export class BillingController {}

@ApiTags('Company — Admin')
@Controller('companies/:companyId/admin')
export class AdminController {}

// Public endpoints
@ApiTags('Public — Auth')
@Controller('auth')
export class AuthController {}

@ApiTags('Public — Health')
@Controller('health')
export class HealthController {}
```

### Tag Description Enrichment

Provide rich descriptions for each tag group:

```typescript
const config = new DocumentBuilder()
  .addTag(
    'Domain — Recipients',
    'CRUD operations on recipients within a single domain. '
    + 'All endpoints require `domainId` path parameter and `x-workspace-id` header. '
    + 'Recipients are unique per domain (email is the natural key).',
  )
  .addTag(
    'Workspace — Dashboards',
    'Cross-domain analytics and reporting within a workspace. '
    + 'Aggregates data across all domains the workspace owns. '
    + 'Requires `x-workspace-id` header.',
  )
  .addTag(
    'Company — Billing',
    'Subscription management, usage tracking, and invoicing. '
    + 'Requires `x-company-id` header. Only company admins can access.',
  )
  .build();
```

---

## Authentication in Swagger UI

### JWT Token Input

The `@ApiBearerAuth('access-token')` decorator enables the Authorize button.
Users click it, paste their JWT, and all subsequent requests include it.

### Auto-Login Flow for Development

```typescript
// Only in development — pre-fill a dev token
if (process.env.NODE_ENV === 'development') {
  SwaggerModule.setup('api/docs', app, document, {
    swaggerOptions: {
      persistAuthorization: true,
      // Pre-fill the auth dialog with a dev token
      authAction: {
        'access-token': {
          name: 'access-token',
          schema: { type: 'http', scheme: 'bearer' },
          value: process.env.DEV_JWT_TOKEN || '',
        },
      },
    },
  });
}
```

### Multiple Security Schemes Combined

```typescript
// Controller requiring both JWT and workspace header
@ApiBearerAuth('access-token')
@ApiSecurity('workspace-id')
@Controller('domains/:domainId/recipients')
export class RecipientsController {}

// Controller requiring JWT and company header
@ApiBearerAuth('access-token')
@ApiSecurity('company-id')
@Controller('companies/:companyId/billing')
export class BillingController {}
```

---

## Example Values Reference

### Standard Types with Examples

Use these consistently across all DTOs:

```typescript
// UUID fields
@ApiProperty({
  format: 'uuid',
  example: 'b3d7f1a2-5e8c-4b9d-a1f3-7c2e8d9b4a6f',
})
id: string;

// Email
@ApiProperty({
  format: 'email',
  example: 'john.doe@example.com',
})
email: string;

// Date-time (ISO 8601)
@ApiProperty({
  format: 'date-time',
  example: '2024-03-15T10:30:00Z',
})
createdAt: string;

// Date only (ISO 8601)
@ApiProperty({
  format: 'date',
  example: '2024-03-15',
})
startDate: string;

// Number (integer)
@ApiProperty({
  type: 'integer',
  minimum: 0,
  example: 1250,
})
total: number;

// Number (float / percentage)
@ApiProperty({
  type: 'number',
  format: 'float',
  minimum: 0,
  maximum: 100,
  example: 45.2,
})
percentUsed: number;

// Boolean
@ApiProperty({
  type: 'boolean',
  example: true,
  description: 'Whether the recipient has opted in to communications',
})
optedIn: boolean;

// Enum
@ApiProperty({
  enum: ['active', 'inactive', 'bounced', 'unsubscribed'],
  example: 'active',
})
status: string;

// Array of strings
@ApiProperty({
  type: [String],
  example: ['vip', 'enterprise', 'Q1-2024'],
})
tags: string[];

// Array of objects
@ApiProperty({
  type: 'array',
  items: {
    type: 'object',
    properties: {
      field: { type: 'string', example: 'email' },
      message: { type: 'string', example: 'Invalid format' },
    },
  },
})
errors: { field: string; message: string }[];

// Nested JSON object
@ApiProperty({
  type: 'object',
  additionalProperties: true,
  example: { department: 'Engineering', level: 'Senior', startDate: '2024-01-15' },
})
customFields: Record<string, unknown>;

// URL
@ApiProperty({
  format: 'uri',
  example: 'https://example.com/avatar/john.png',
})
avatarUrl: string;

// Phone number
@ApiProperty({
  type: 'string',
  pattern: '^\\+[1-9]\\d{1,14}$',
  example: '+14155552671',
})
phone: string;

// Duration (ISO 8601)
@ApiProperty({
  type: 'string',
  example: 'PT1H30M',
  description: 'Duration in ISO 8601 format',
})
duration: string;
```

---

## Multi-Tenant Headers

### Global Parameter via Plugin

Apply `x-workspace-id` as a required header to most endpoints using a Swagger plugin:

```typescript
// swagger-plugins/workspace-header.plugin.ts
import { OpenAPIObject } from '@nestjs/swagger';

export function addWorkspaceHeaderPlugin(document: OpenAPIObject): OpenAPIObject {
  const publicPaths = ['/health', '/auth/login', '/auth/register', '/auth/refresh'];

  for (const [path, methods] of Object.entries(document.paths)) {
    // Skip public endpoints
    if (publicPaths.some(p => path.startsWith(p))) continue;

    for (const [method, operation] of Object.entries(methods as Record<string, any>)) {
      if (typeof operation !== 'object' || !operation.responses) continue;

      // Check if endpoint already has the header defined
      const hasHeader = operation.parameters?.some(
        (p: any) => p.name === 'x-workspace-id' && p.in === 'header',
      );

      if (!hasHeader) {
        operation.parameters = operation.parameters || [];
        operation.parameters.push({
          name: 'x-workspace-id',
          in: 'header',
          required: true,
          description: 'Workspace UUID for tenant context resolution',
          schema: {
            type: 'string',
            format: 'uuid',
            example: 'ws_a1b2c3d4-5678-90ab-cdef-1234567890ab',
          },
        });
      }
    }
  }

  return document;
}

// main.ts — apply plugin after document creation
let document = SwaggerModule.createDocument(app, config);
document = addWorkspaceHeaderPlugin(document);
SwaggerModule.setup('api/docs', app, document);
```

### Per-Endpoint Header Override

When a specific endpoint needs different headers (e.g., company-scoped):

```typescript
@ApiHeader({
  name: 'x-company-id',
  required: true,
  description: 'Company UUID — overrides the default x-workspace-id for this endpoint',
  schema: { type: 'string', format: 'uuid' },
})
@Get('usage')
async getUsage() {}
```

---

## Export OpenAPI Spec

### JSON and YAML Export Script

```typescript
// scripts/export-openapi.ts
import { NestFactory } from '@nestjs/core';
import { SwaggerModule, DocumentBuilder } from '@nestjs/swagger';
import { writeFileSync } from 'fs';
import { dump } from 'yaml';
import { AppModule } from '../src/app.module';

async function exportSpec() {
  const app = await NestFactory.create(AppModule, { logger: false });

  const config = new DocumentBuilder()
    .setTitle('Platform API')
    .setVersion('1.0')
    .addBearerAuth({ type: 'http', scheme: 'bearer', bearerFormat: 'JWT' }, 'access-token')
    .addApiKey({ type: 'apiKey', name: 'x-workspace-id', in: 'header' }, 'workspace-id')
    .build();

  const document = SwaggerModule.createDocument(app, config);

  writeFileSync('./openapi.json', JSON.stringify(document, null, 2));
  writeFileSync('./openapi.yaml', dump(document));

  console.log('Exported: openapi.json, openapi.yaml');
  console.log(`Paths: ${Object.keys(document.paths).length}`);
  console.log(`Schemas: ${Object.keys(document.components?.schemas || {}).length}`);

  await app.close();
}
exportSpec();
```

### npm Scripts

```json
{
  "scripts": {
    "openapi:export": "ts-node scripts/export-openapi.ts",
    "openapi:validate": "npx @redocly/cli lint ./openapi.json",
    "openapi:diff": "npx openapi-diff ./openapi-previous.json ./openapi.json --fail-on-incompatible",
    "postman:export": "npx openapi-to-postmanv2 -s ./openapi.json -o ./postman-collection.json"
  }
}
```

---

## OpenAPI Validation in CI

### GitHub Actions Workflow

```yaml
# .github/workflows/openapi-check.yml
name: OpenAPI Spec Validation

on:
  pull_request:
    paths:
      - 'src/**/*.controller.ts'
      - 'src/**/*.dto.ts'
      - 'src/**/swagger/**'

jobs:
  validate-openapi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - run: npm ci

      # Generate current spec
      - name: Export OpenAPI spec
        run: npm run openapi:export

      # Lint the spec for completeness
      - name: Lint OpenAPI spec
        run: npx @redocly/cli lint ./openapi.json --config redocly.yaml

      # Check for breaking changes against main branch
      - name: Download previous spec
        run: |
          git show origin/main:openapi.json > openapi-previous.json || echo '{}' > openapi-previous.json

      - name: Detect breaking changes
        run: |
          npx openapi-diff openapi-previous.json openapi.json \
            --fail-on-incompatible

      # Upload spec as artifact
      - name: Upload OpenAPI spec
        uses: actions/upload-artifact@v4
        with:
          name: openapi-spec
          path: |
            openapi.json
            openapi.yaml
```

### Redocly Lint Configuration

```yaml
# redocly.yaml
extends:
  - recommended

rules:
  operation-operationId: error
  operation-summary: error
  operation-description: warn
  tag-description: warn
  no-unresolved-refs: error
  no-ambiguous-paths: error
  path-parameters-defined: error
  operation-2xx-response: error
  operation-4xx-response: warn

  # Custom rules for multi-tenant API
  rule/require-workspace-header:
    severity: warn
    message: 'Domain-scoped endpoints should document x-workspace-id header'

  rule/require-auth:
    severity: error
    message: 'All non-public endpoints must have security defined'
```

### Breaking Change Categories

| Change | Breaking? | Action |
|--------|-----------|--------|
| Remove endpoint | Yes | New version required |
| Rename path parameter | Yes | New version required |
| Add required request field | Yes | New version required |
| Remove response field | Yes | New version required |
| Change field type | Yes | New version required |
| Add optional request field | No | Patch version bump |
| Add response field | No | Patch version bump |
| Add new endpoint | No | Minor version bump |
| Update description | No | No version change |

---

## Postman Collection Generation

### From OpenAPI Spec

```bash
# Install converter
npm install -g openapi-to-postmanv2

# Generate collection
openapi2postmanv2 -s ./openapi.json -o ./postman-collection.json \
  -p folderStrategy=Tags \
  -p requestParametersResolution=Example
```

### Postman Environment Template

```json
{
  "name": "Platform API - Development",
  "values": [
    {
      "key": "baseUrl",
      "value": "http://localhost:3000",
      "type": "default"
    },
    {
      "key": "accessToken",
      "value": "",
      "type": "secret"
    },
    {
      "key": "workspaceId",
      "value": "",
      "type": "default"
    },
    {
      "key": "companyId",
      "value": "",
      "type": "default"
    },
    {
      "key": "domainId",
      "value": "",
      "type": "default"
    }
  ]
}
```

### Pre-Request Script for Auto-Auth

```javascript
// Postman pre-request script — auto-refresh JWT
const tokenExpiry = pm.environment.get('tokenExpiry');
if (!tokenExpiry || Date.now() > parseInt(tokenExpiry)) {
  pm.sendRequest({
    url: pm.environment.get('baseUrl') + '/auth/login',
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
    body: {
      mode: 'raw',
      raw: JSON.stringify({
        email: pm.environment.get('testEmail'),
        password: pm.environment.get('testPassword'),
      }),
    },
  }, (err, response) => {
    const body = response.json();
    pm.environment.set('accessToken', body.data.accessToken);
    pm.environment.set('tokenExpiry', Date.now() + 3500000); // ~58 min
  });
}
```

---

## Redoc for Public-Facing Docs

### NestJS Integration

```typescript
// Install: npm install nestjs-redoc

import { RedocModule, RedocOptions } from 'nestjs-redoc';

const redocOptions: RedocOptions = {
  title: 'Platform API Reference',
  logo: {
    url: 'https://example.com/logo.png',
    altText: 'Platform Logo',
  },
  sortPropsAlphabetically: true,
  hideDownloadButton: false,
  hideHostname: false,
  noAutoAuth: false,
  pathInMiddlePanel: true,
  theme: {
    colors: {
      primary: { main: '#2563eb' },
    },
    typography: {
      fontFamily: '"Inter", -apple-system, sans-serif',
      headings: { fontFamily: '"Inter", -apple-system, sans-serif' },
    },
    sidebar: {
      width: '260px',
      backgroundColor: '#f8fafc',
    },
    rightPanel: {
      backgroundColor: '#1e293b',
    },
  },
};

// After creating the Swagger document:
await RedocModule.setup('/api/reference', app, document, redocOptions);
```

### When to Use Redoc vs Swagger UI

| Feature | Swagger UI | Redoc |
|---------|-----------|-------|
| Try-it-out (interactive) | Yes | No |
| Code samples | Limited | Yes (multi-language) |
| Three-panel layout | No | Yes |
| SEO-friendly | No | Yes |
| Public-facing docs | No | Yes |
| Internal developer portal | Yes | Yes |

**Recommendation:**
- **Internal teams**: Swagger UI at `/api/docs` (interactive testing)
- **Public/partner docs**: Redoc at `/api/reference` (polished, read-only)
- Both served from the same OpenAPI spec — single source of truth
