---
name: api-docs-skill
description: API documentation, OpenAPI/Swagger generation, versioning, SDK generation, and developer portal patterns for multi-tenant SaaS NestJS APIs. Auto-generates docs from decorators, maintains changelog, produces TypeScript SDK for frontend consumption. Trigger when documenting APIs, setting up Swagger, versioning endpoints, generating SDKs, creating Postman collections, or building a developer portal.
---

# SKILL: API Documentation, OpenAPI/Swagger, Versioning & SDK Generation

## Stack

NestJS + `@nestjs/swagger` + OpenAPI 3.1 + TypeScript SDK + Redoc

---

## IDENTITY

You are a senior API documentation architect. You:

1. Instrument every endpoint with complete Swagger decorators (not just `@ApiTags`)
2. Document the multi-tenant header contract so consumers never guess
3. Generate typed SDKs that replace hand-written fetch calls
4. Enforce a documentation checklist before any endpoint ships
5. Maintain a versioned changelog so breaking changes are always communicated

---

## CORE PRINCIPLES

### 1. Decorators Are the Source of Truth

The OpenAPI spec is generated FROM decorators. If a decorator is missing, the spec is wrong.
Never maintain a separate OpenAPI YAML by hand. The NestJS code IS the spec.

### 2. Every Endpoint Gets Full Coverage

No endpoint ships without:
- `@ApiTags()` - module grouping
- `@ApiOperation()` - human-readable summary + description
- `@ApiParam()` - every path parameter documented
- `@ApiHeader()` - required tenant headers
- `@ApiBody()` - request DTO with examples
- `@ApiResponse()` - every possible status code
- `@ApiBearerAuth()` - auth requirement
- `@ApiQuery()` - pagination and filter params

### 3. DTOs Are Self-Documenting

Every DTO field has `@ApiProperty()` with description, example, and required flag.
The DTO IS the documentation. If the DTO is incomplete, the docs are incomplete.

### 4. Multi-Tenant Scoping Is Visible

Every endpoint clearly states its tenant scope:
- **Domain-scoped**: requires `domainId` path param, operates on domain data
- **Workspace-scoped**: requires `x-workspace-id` header, cross-domain operations
- **Company-scoped**: requires `x-company-id` header, billing/admin operations
- **Public**: no tenant context required (health, auth)

---

## SWAGGER MODULE SETUP

> Read `openapi.md` for the full module configuration, theming, and CI integration.

### Minimal Bootstrap

```typescript
// main.ts
import { NestFactory } from '@nestjs/core';
import { SwaggerModule, DocumentBuilder } from '@nestjs/swagger';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  const config = new DocumentBuilder()
    .setTitle('Platform API')
    .setDescription('Multi-tenant SaaS API documentation')
    .setVersion('1.0')
    .addBearerAuth(
      { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' },
      'access-token',
    )
    .addApiKey(
      { type: 'apiKey', name: 'x-workspace-id', in: 'header' },
      'workspace-id',
    )
    .addApiKey(
      { type: 'apiKey', name: 'x-company-id', in: 'header' },
      'company-id',
    )
    .addServer('http://localhost:3000', 'Local Development')
    .addServer('https://api.staging.example.com', 'Staging')
    .addServer('https://api.example.com', 'Production')
    .build();

  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('api/docs', app, document, {
    swaggerOptions: {
      persistAuthorization: true,
      tagsSorter: 'alpha',
      operationsSorter: 'alpha',
    },
  });

  await app.listen(3000);
}
bootstrap();
```

---

## DECORATOR PATTERNS — Complete Reference

### Domain-Scoped Endpoint (CRUD — Hot Path)

```typescript
import {
  Controller, Get, Post, Patch, Delete, Param, Body, Query,
  ParseUUIDPipe, HttpStatus,
} from '@nestjs/common';
import {
  ApiTags, ApiOperation, ApiParam, ApiHeader, ApiBody,
  ApiResponse, ApiBearerAuth, ApiQuery, ApiExtraModels,
} from '@nestjs/swagger';

@ApiTags('Recipients')
@ApiBearerAuth('access-token')
@Controller('domains/:domainId/recipients')
export class RecipientsController {

  @Get()
  @ApiOperation({
    summary: 'List recipients in a domain',
    description: 'Returns a paginated list of recipients scoped to the given domain. '
      + 'Supports filtering by status, tag, and custom field values. '
      + 'Results are ordered by createdAt descending.',
  })
  @ApiParam({
    name: 'domainId',
    type: 'string',
    format: 'uuid',
    description: 'The domain to list recipients from',
    example: 'b3d7f1a2-5e8c-4b9d-a1f3-7c2e8d9b4a6f',
  })
  @ApiHeader({
    name: 'x-workspace-id',
    required: true,
    description: 'Workspace context for tenant resolution',
    example: 'ws_a1b2c3d4-5678-90ab-cdef-1234567890ab',
  })
  @ApiQuery({
    name: 'page',
    required: false,
    type: Number,
    description: 'Page number (1-indexed)',
    example: 1,
  })
  @ApiQuery({
    name: 'pageSize',
    required: false,
    type: Number,
    description: 'Items per page (max 100)',
    example: 25,
  })
  @ApiQuery({
    name: 'status',
    required: false,
    enum: ['active', 'inactive', 'bounced', 'unsubscribed'],
    description: 'Filter by recipient status',
  })
  @ApiQuery({
    name: 'search',
    required: false,
    type: String,
    description: 'Full-text search across name and email',
  })
  @ApiResponse({
    status: HttpStatus.OK,
    description: 'Paginated list of recipients',
    schema: {
      type: 'object',
      properties: {
        data: {
          type: 'array',
          items: { $ref: '#/components/schemas/RecipientResponseDto' },
        },
        meta: {
          type: 'object',
          properties: {
            total: { type: 'number', example: 1250 },
            page: { type: 'number', example: 1 },
            pageSize: { type: 'number', example: 25 },
            hasMore: { type: 'boolean', example: true },
          },
        },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.UNAUTHORIZED,
    description: 'Missing or invalid JWT token',
  })
  @ApiResponse({
    status: HttpStatus.FORBIDDEN,
    description: 'User does not have access to this domain',
  })
  @ApiResponse({
    status: HttpStatus.NOT_FOUND,
    description: 'Domain not found',
  })
  async list(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Query() filter: ListRecipientsQueryDto,
  ) {
    // Implementation
  }

  @Post()
  @ApiOperation({
    summary: 'Create a recipient',
    description: 'Creates a new recipient in the specified domain. '
      + 'Email must be unique within the domain. '
      + 'Custom fields are validated against workspace-level field definitions.',
  })
  @ApiParam({
    name: 'domainId',
    type: 'string',
    format: 'uuid',
    description: 'The domain to create the recipient in',
  })
  @ApiHeader({
    name: 'x-workspace-id',
    required: true,
    description: 'Workspace context for tenant resolution',
  })
  @ApiBody({
    type: CreateRecipientDto,
    examples: {
      basic: {
        summary: 'Basic recipient',
        value: {
          email: 'john.doe@example.com',
          firstName: 'John',
          lastName: 'Doe',
          status: 'active',
        },
      },
      withCustomFields: {
        summary: 'Recipient with custom fields',
        value: {
          email: 'jane.smith@corp.com',
          firstName: 'Jane',
          lastName: 'Smith',
          status: 'active',
          customFields: {
            department: 'Engineering',
            employeeId: 'EMP-1234',
            startDate: '2024-01-15',
          },
        },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.CREATED,
    description: 'Recipient created successfully',
    type: RecipientResponseDto,
  })
  @ApiResponse({
    status: HttpStatus.CONFLICT,
    description: 'Email already exists in this domain',
    schema: {
      type: 'object',
      properties: {
        statusCode: { type: 'number', example: 409 },
        message: { type: 'string', example: 'Recipient with this email already exists in domain' },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.UNPROCESSABLE_ENTITY,
    description: 'Validation failed (invalid custom field, bad email format)',
  })
  async create(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Body() dto: CreateRecipientDto,
  ) {
    // Implementation
  }

  @Patch(':id')
  @ApiOperation({
    summary: 'Update a recipient',
    description: 'Partially updates a recipient. Only provided fields are modified.',
  })
  @ApiParam({ name: 'domainId', type: 'string', format: 'uuid' })
  @ApiParam({
    name: 'id',
    type: 'string',
    format: 'uuid',
    description: 'Recipient ID',
  })
  @ApiHeader({ name: 'x-workspace-id', required: true })
  @ApiBody({ type: UpdateRecipientDto })
  @ApiResponse({ status: HttpStatus.OK, type: RecipientResponseDto })
  @ApiResponse({ status: HttpStatus.NOT_FOUND, description: 'Recipient not found' })
  async update(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateRecipientDto,
  ) {
    // Implementation
  }

  @Delete(':id')
  @ApiOperation({
    summary: 'Soft-delete a recipient',
    description: 'Marks the recipient as deleted. Data is retained for audit purposes.',
  })
  @ApiParam({ name: 'domainId', type: 'string', format: 'uuid' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiHeader({ name: 'x-workspace-id', required: true })
  @ApiResponse({ status: HttpStatus.OK, description: 'Recipient soft-deleted' })
  @ApiResponse({ status: HttpStatus.NOT_FOUND, description: 'Recipient not found' })
  async remove(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Param('id', ParseUUIDPipe) id: string,
  ) {
    // Implementation
  }
}
```

### Workspace-Scoped Endpoint (Dashboards / Cross-Domain)

```typescript
@ApiTags('Dashboards')
@ApiBearerAuth('access-token')
@Controller('workspaces/:workspaceId/dashboards')
export class DashboardsController {

  @Get('recipients/stats')
  @ApiOperation({
    summary: 'Get recipient statistics across all domains in workspace',
    description: 'Aggregates recipient counts, status breakdown, and growth trends '
      + 'across all domains in the workspace. Used for workspace-level dashboard.',
  })
  @ApiParam({
    name: 'workspaceId',
    type: 'string',
    format: 'uuid',
    description: 'Workspace to aggregate stats for',
  })
  @ApiHeader({
    name: 'x-workspace-id',
    required: true,
    description: 'Must match the workspaceId path parameter',
  })
  @ApiQuery({
    name: 'dateFrom',
    required: false,
    type: String,
    description: 'Start date for trend data (ISO 8601)',
    example: '2024-01-01',
  })
  @ApiQuery({
    name: 'dateTo',
    required: false,
    type: String,
    description: 'End date for trend data (ISO 8601)',
    example: '2024-12-31',
  })
  @ApiResponse({
    status: HttpStatus.OK,
    description: 'Workspace-level recipient statistics',
    schema: {
      type: 'object',
      properties: {
        data: {
          type: 'object',
          properties: {
            totalRecipients: { type: 'number', example: 45230 },
            byStatus: {
              type: 'object',
              properties: {
                active: { type: 'number', example: 40100 },
                inactive: { type: 'number', example: 3200 },
                bounced: { type: 'number', example: 1500 },
                unsubscribed: { type: 'number', example: 430 },
              },
            },
            byDomain: {
              type: 'array',
              items: {
                type: 'object',
                properties: {
                  domainId: { type: 'string', format: 'uuid' },
                  domainName: { type: 'string', example: 'marketing.example.com' },
                  count: { type: 'number', example: 12500 },
                },
              },
            },
            trend: {
              type: 'array',
              items: {
                type: 'object',
                properties: {
                  date: { type: 'string', example: '2024-03-01' },
                  added: { type: 'number', example: 150 },
                  removed: { type: 'number', example: 12 },
                },
              },
            },
          },
        },
      },
    },
  })
  async getRecipientStats(
    @Param('workspaceId', ParseUUIDPipe) workspaceId: string,
    @Query() filter: DashboardFilterDto,
  ) {
    // Implementation
  }
}
```

### Company-Scoped Endpoint (Billing / Admin)

```typescript
@ApiTags('Billing')
@ApiBearerAuth('access-token')
@Controller('companies/:companyId/billing')
export class BillingController {

  @Get('usage')
  @ApiOperation({
    summary: 'Get company usage and subscription limits',
    description: 'Returns current resource usage vs plan limits. '
      + 'Includes recipient count, seat count, and storage across all workspaces.',
  })
  @ApiParam({
    name: 'companyId',
    type: 'string',
    format: 'uuid',
    description: 'Company to retrieve billing data for',
  })
  @ApiHeader({
    name: 'x-company-id',
    required: true,
    description: 'Company context — must match companyId path param',
  })
  @ApiResponse({
    status: HttpStatus.OK,
    description: 'Current usage and limits',
    schema: {
      type: 'object',
      properties: {
        data: {
          type: 'object',
          properties: {
            plan: { type: 'string', example: 'business' },
            status: { type: 'string', example: 'active' },
            recipients: {
              type: 'object',
              properties: {
                used: { type: 'number', example: 45230 },
                limit: { type: 'number', example: 100000 },
                percentUsed: { type: 'number', example: 45.2 },
              },
            },
            seats: {
              type: 'object',
              properties: {
                used: { type: 'number', example: 12 },
                limit: { type: 'number', example: 25 },
              },
            },
            billingPeriod: {
              type: 'object',
              properties: {
                start: { type: 'string', example: '2024-03-01' },
                end: { type: 'string', example: '2024-03-31' },
              },
            },
          },
        },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.FORBIDDEN,
    description: 'User is not a company admin',
  })
  async getUsage(
    @Param('companyId', ParseUUIDPipe) companyId: string,
  ) {
    // Implementation
  }
}
```

### Async / Bulk Endpoint (Job Queue Return)

```typescript
@ApiTags('Recipients')
@ApiBearerAuth('access-token')
@Controller('domains/:domainId/recipients')
export class RecipientsBulkController {

  @Post('bulk')
  @ApiOperation({
    summary: 'Bulk update recipients',
    description: 'Updates multiple recipients matching the filter criteria. '
      + 'If >1000 recipients match, the operation is queued and a jobId is returned. '
      + 'Track progress via SSE at /jobs/:jobId/progress.',
  })
  @ApiParam({ name: 'domainId', type: 'string', format: 'uuid' })
  @ApiHeader({ name: 'x-workspace-id', required: true })
  @ApiBody({
    type: BulkUpdateRecipientsDto,
    examples: {
      byFilter: {
        summary: 'Update by filter (may be async)',
        value: {
          filter: { status: 'inactive', tags: ['churned'] },
          update: { status: 'unsubscribed' },
        },
      },
      byIds: {
        summary: 'Update by explicit IDs (usually sync)',
        value: {
          ids: ['uuid-1', 'uuid-2', 'uuid-3'],
          update: { status: 'active' },
        },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.OK,
    description: 'Sync result (<=1000 affected)',
    schema: {
      type: 'object',
      properties: {
        affected: { type: 'number', example: 150 },
        status: { type: 'string', example: 'completed' },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.ACCEPTED,
    description: 'Async result (>1000 affected, queued)',
    schema: {
      type: 'object',
      properties: {
        jobId: { type: 'string', example: 'bulk-op:b3d7f1a2' },
        status: { type: 'string', example: 'queued' },
        estimated: { type: 'number', example: 12500 },
      },
    },
  })
  @ApiResponse({
    status: HttpStatus.PAYMENT_REQUIRED,
    description: 'Would exceed subscription limit',
  })
  async bulkUpdate(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Body() dto: BulkUpdateRecipientsDto,
  ) {
    // Implementation
  }

  @Post('import')
  @ApiOperation({
    summary: 'Import recipients from file',
    description: 'Processes an uploaded CSV/XLSX file. Always async. '
      + 'Flow: upload → parse → staging → preview → commit. '
      + 'Returns jobId for progress tracking.',
  })
  @ApiParam({ name: 'domainId', type: 'string', format: 'uuid' })
  @ApiHeader({ name: 'x-workspace-id', required: true })
  @ApiBody({
    schema: {
      type: 'object',
      properties: {
        fileKey: {
          type: 'string',
          description: 'S3 key from presigned upload',
          example: 'imports/ws_abc123/recipients_2024-03.csv',
        },
        mapping: {
          type: 'object',
          description: 'Column name → field name mapping',
          example: {
            'Email Address': 'email',
            'First Name': 'firstName',
            'Last Name': 'lastName',
            'Department': 'customFields.department',
          },
        },
      },
      required: ['fileKey', 'mapping'],
    },
  })
  @ApiResponse({
    status: HttpStatus.ACCEPTED,
    description: 'Import job queued',
    schema: {
      type: 'object',
      properties: {
        jobId: { type: 'string', example: 'import:b3d7f1a2:1710000000' },
        status: { type: 'string', example: 'queued' },
      },
    },
  })
  async importRecipients(
    @Param('domainId', ParseUUIDPipe) domainId: string,
    @Body() dto: ImportRecipientsDto,
  ) {
    // Implementation
  }
}
```

---

## DTO DOCUMENTATION PATTERNS

### Request DTO with Full @ApiProperty Coverage

```typescript
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEmail, IsString, IsOptional, IsEnum, IsObject, MaxLength } from 'class-validator';

export class CreateRecipientDto {
  @ApiProperty({
    description: 'Recipient email address. Must be unique within the domain.',
    example: 'john.doe@example.com',
    format: 'email',
    maxLength: 255,
  })
  @IsEmail()
  @MaxLength(255)
  email: string;

  @ApiProperty({
    description: 'First name of the recipient',
    example: 'John',
    maxLength: 100,
  })
  @IsString()
  @MaxLength(100)
  firstName: string;

  @ApiProperty({
    description: 'Last name of the recipient',
    example: 'Doe',
    maxLength: 100,
  })
  @IsString()
  @MaxLength(100)
  lastName: string;

  @ApiProperty({
    description: 'Recipient status',
    enum: ['active', 'inactive'],
    default: 'active',
    example: 'active',
  })
  @IsEnum(['active', 'inactive'])
  status: 'active' | 'inactive' = 'active';

  @ApiPropertyOptional({
    description: 'Custom field values. Keys must match workspace-level field definitions. '
      + 'Values are validated against field type (text, number, date, select, etc.).',
    example: { department: 'Engineering', employeeId: 'EMP-1234' },
    type: 'object',
    additionalProperties: true,
  })
  @IsOptional()
  @IsObject()
  customFields?: Record<string, unknown>;

  @ApiPropertyOptional({
    description: 'Tags for segmentation',
    example: ['vip', 'enterprise'],
    type: [String],
  })
  @IsOptional()
  @IsString({ each: true })
  tags?: string[];
}
```

### Response DTO

```typescript
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

export class RecipientResponseDto {
  @ApiProperty({
    description: 'Unique identifier',
    example: 'b3d7f1a2-5e8c-4b9d-a1f3-7c2e8d9b4a6f',
    format: 'uuid',
  })
  id: string;

  @ApiProperty({
    description: 'Domain this recipient belongs to',
    example: 'a1b2c3d4-5678-90ab-cdef-1234567890ab',
    format: 'uuid',
  })
  domainId: string;

  @ApiProperty({ example: 'john.doe@example.com' })
  email: string;

  @ApiProperty({ example: 'John' })
  firstName: string;

  @ApiProperty({ example: 'Doe' })
  lastName: string;

  @ApiProperty({ enum: ['active', 'inactive', 'bounced', 'unsubscribed'], example: 'active' })
  status: string;

  @ApiPropertyOptional({
    description: 'Custom field values',
    example: { department: 'Engineering' },
  })
  customFields?: Record<string, unknown>;

  @ApiProperty({
    description: 'When the recipient was created',
    example: '2024-03-15T10:30:00Z',
    format: 'date-time',
  })
  createdAt: string;

  @ApiProperty({
    description: 'When the recipient was last updated',
    example: '2024-03-15T14:22:00Z',
    format: 'date-time',
  })
  updatedAt: string;
}
```

### Pagination Meta DTO (Reusable)

```typescript
export class PaginationMetaDto {
  @ApiProperty({ description: 'Total number of records matching the query', example: 1250 })
  total: number;

  @ApiProperty({ description: 'Current page number (1-indexed)', example: 1 })
  page: number;

  @ApiProperty({ description: 'Number of items per page', example: 25 })
  pageSize: number;

  @ApiProperty({ description: 'Whether more pages exist', example: true })
  hasMore: boolean;
}
```

### Error Response DTO

```typescript
export class ErrorResponseDto {
  @ApiProperty({ description: 'HTTP status code', example: 400 })
  statusCode: number;

  @ApiProperty({ description: 'Human-readable error message', example: 'Validation failed' })
  message: string;

  @ApiPropertyOptional({
    description: 'Field-level validation errors',
    example: [
      { field: 'email', message: 'Invalid email format' },
      { field: 'firstName', message: 'Must not be empty' },
    ],
  })
  errors?: { field: string; message: string }[];
}
```

---

## MULTI-TENANT API DOCUMENTATION STRATEGY

### Scope Decorator (Custom)

Create a custom decorator to mark endpoint scope in docs:

```typescript
import { applyDecorators } from '@nestjs/common';
import { ApiHeader, ApiOperation } from '@nestjs/swagger';

export type TenantScope = 'domain' | 'workspace' | 'company' | 'public';

export function ApiTenantScope(scope: TenantScope, operation: {
  summary: string;
  description?: string;
}) {
  const decorators = [
    ApiOperation({
      summary: `[${scope.toUpperCase()}] ${operation.summary}`,
      description: operation.description,
    }),
  ];

  if (scope === 'domain' || scope === 'workspace') {
    decorators.push(
      ApiHeader({
        name: 'x-workspace-id',
        required: true,
        description: 'Workspace context for tenant resolution',
        schema: { type: 'string', format: 'uuid' },
      }),
    );
  }

  if (scope === 'company') {
    decorators.push(
      ApiHeader({
        name: 'x-company-id',
        required: true,
        description: 'Company context for billing/admin operations',
        schema: { type: 'string', format: 'uuid' },
      }),
    );
  }

  return applyDecorators(...decorators);
}

// Usage:
@ApiTenantScope('domain', {
  summary: 'List recipients in a domain',
  description: 'Returns paginated recipients scoped to the domain.',
})
```

### Grouping by Scope in Swagger UI

Use tag descriptions to group endpoints by scope:

```typescript
// main.ts — after DocumentBuilder
const config = new DocumentBuilder()
  // ... base config
  .addTag('Domain — Recipients', 'CRUD operations scoped to a single domain')
  .addTag('Domain — Campaigns', 'Campaign management within a domain')
  .addTag('Workspace — Dashboards', 'Cross-domain reporting within a workspace')
  .addTag('Workspace — Settings', 'Workspace-level configuration')
  .addTag('Company — Billing', 'Subscription and usage for the entire company')
  .addTag('Company — Admin', 'Company administration and user management')
  .addTag('Public — Auth', 'Authentication endpoints (no tenant context)')
  .addTag('Public — Health', 'Health check and status endpoints')
  .build();
```

---

## STANDARDIZED RESPONSE SHAPES

Document these consistently across all endpoints:

### Single Entity

```typescript
@ApiResponse({
  status: 200,
  schema: {
    type: 'object',
    properties: {
      data: { $ref: '#/components/schemas/EntityDto' },
    },
  },
})
```

### Paginated List

```typescript
@ApiResponse({
  status: 200,
  schema: {
    type: 'object',
    properties: {
      data: {
        type: 'array',
        items: { $ref: '#/components/schemas/EntityDto' },
      },
      meta: { $ref: '#/components/schemas/PaginationMetaDto' },
    },
  },
})
```

### Async Job

```typescript
@ApiResponse({
  status: 202,
  description: 'Operation queued for background processing',
  schema: {
    type: 'object',
    properties: {
      jobId: { type: 'string', example: 'bulk-op:abc123' },
      status: { type: 'string', enum: ['queued', 'processing'], example: 'queued' },
      estimated: { type: 'number', description: 'Estimated items to process', example: 12500 },
    },
  },
})
```

### Error (All Endpoints)

Every endpoint should include these error responses:

```typescript
// Apply to all authenticated endpoints
@ApiResponse({ status: 401, description: 'Missing or invalid JWT token', type: ErrorResponseDto })
@ApiResponse({ status: 403, description: 'Insufficient permissions for this resource', type: ErrorResponseDto })
@ApiResponse({ status: 500, description: 'Internal server error', type: ErrorResponseDto })

// Apply to mutation endpoints
@ApiResponse({ status: 400, description: 'Validation failed', type: ErrorResponseDto })
@ApiResponse({ status: 422, description: 'Business rule violation', type: ErrorResponseDto })

// Apply to tenant-scoped endpoints
@ApiResponse({ status: 402, description: 'Subscription limit exceeded', type: ErrorResponseDto })
@ApiResponse({ status: 404, description: 'Resource not found in tenant scope', type: ErrorResponseDto })
```

---

## API VERSIONING STRATEGY

### URL Versioning (Recommended)

```typescript
// main.ts
app.enableVersioning({
  type: VersioningType.URI,
  defaultVersion: '1',
  prefix: 'v',
});

// Controller — version-specific
@Controller({ path: 'domains/:domainId/recipients', version: '1' })
export class RecipientsV1Controller { }

// Controller — new version with breaking changes
@Controller({ path: 'domains/:domainId/recipients', version: '2' })
export class RecipientsV2Controller { }
```

### Deprecation Decorators

```typescript
import { ApiExtension } from '@nestjs/swagger';

// Mark deprecated endpoint
@ApiOperation({
  summary: 'List recipients (DEPRECATED)',
  description: 'Use v2 endpoint instead. This endpoint will be removed on 2025-06-01.',
  deprecated: true,
})
```

### Version-Specific Swagger Documents

```typescript
// main.ts — separate docs per version
const v1Config = new DocumentBuilder()
  .setTitle('Platform API v1')
  .setVersion('1.0')
  .build();

const v2Config = new DocumentBuilder()
  .setTitle('Platform API v2')
  .setVersion('2.0')
  .build();

const v1Document = SwaggerModule.createDocument(app, v1Config, {
  include: [RecipientsV1Module, CampaignsV1Module],
});
const v2Document = SwaggerModule.createDocument(app, v2Config, {
  include: [RecipientsV2Module, CampaignsV2Module],
});

SwaggerModule.setup('api/v1/docs', app, v1Document);
SwaggerModule.setup('api/v2/docs', app, v2Document);
```

---

## API CHANGELOG STRATEGY

Maintain a changelog at the API level:

### Format

```markdown
# API Changelog

## [v1.5.0] - 2024-03-15
### Added
- `GET /v1/domains/:domainId/recipients/export` — export recipients as CSV
- `customFields` filter support on `GET /v1/domains/:domainId/recipients`

### Changed (Non-Breaking)
- `GET /v1/workspaces/:wsId/dashboards/stats` now includes `trend` array

### Deprecated
- `GET /v1/domains/:domainId/recipients?tag=X` — use `tags[]=X` instead (removal: 2025-06-01)

## [v2.0.0] - 2024-04-01 (BREAKING)
### Breaking Changes
- Response wrapper changed: `{ items: [] }` → `{ data: [], meta: {} }`
- `GET /v1/recipients` removed — use `/v2/domains/:domainId/recipients`
- `x-tenant-id` header renamed to `x-workspace-id`

### Migration Guide
1. Update response parsing to use `data` instead of `items`
2. Add `meta.hasMore` check for pagination (replaces `nextCursor`)
3. Rename header from `x-tenant-id` to `x-workspace-id`
```

### Breaking Change Detection in CI

```yaml
# .github/workflows/openapi-check.yml
- name: Detect breaking changes
  run: |
    npx openapi-diff ./openapi-previous.json ./openapi-current.json \
      --fail-on-incompatible
```

---

## MASTER CHECKLIST — Run Before Shipping ANY Endpoint

### Decorator Coverage
- [ ] `@ApiTags()` — endpoint grouped by module
- [ ] `@ApiOperation()` — summary + description present
- [ ] `@ApiParam()` — every path parameter documented with type, format, example
- [ ] `@ApiHeader()` — `x-workspace-id` or `x-company-id` documented if tenant-scoped
- [ ] `@ApiBody()` — request DTO with at least 2 examples (basic + complex)
- [ ] `@ApiResponse()` — success response with schema or type reference
- [ ] `@ApiResponse()` — 401, 403, 500 error responses on all authenticated endpoints
- [ ] `@ApiResponse()` — 400, 422 on all mutation endpoints
- [ ] `@ApiResponse()` — 402 on endpoints that check subscription limits
- [ ] `@ApiResponse()` — 404 on endpoints with path parameters
- [ ] `@ApiBearerAuth()` — present on all authenticated endpoints
- [ ] `@ApiQuery()` — pagination params (page, pageSize) on all list endpoints

### DTO Coverage
- [ ] Every field has `@ApiProperty()` or `@ApiPropertyOptional()`
- [ ] Every `@ApiProperty()` has `description` and `example`
- [ ] Enums have `enum` array specified
- [ ] Dates have `format: 'date-time'`
- [ ] UUIDs have `format: 'uuid'`
- [ ] Optional fields use `@ApiPropertyOptional()` (not `required: false`)
- [ ] Nested objects have their own DTO class (not inline `type: 'object'`)

### Multi-Tenant
- [ ] Endpoint scope is clear (domain / workspace / company / public)
- [ ] Scope is visible in Swagger UI (via tag name or `@ApiTenantScope`)
- [ ] Required headers match the scope level
- [ ] Path parameters match the scope level

### Response Shape
- [ ] Single entity: `{ data: T }`
- [ ] List: `{ data: T[], meta: PaginationMetaDto }`
- [ ] Async: `{ jobId, status, estimated? }`
- [ ] Error: `{ statusCode, message, errors? }`
- [ ] All shapes are consistent across the entire API

### Versioning
- [ ] New endpoints use the current version
- [ ] Deprecated endpoints have `deprecated: true` and removal date
- [ ] Breaking changes go in a new version (never modify existing version contract)
- [ ] Changelog updated for every API change

### SDK Impact
- [ ] Generated SDK reflects the new endpoint (regenerate after spec changes)
- [ ] SDK types match the documented DTOs
- [ ] SDK examples in README updated if new endpoint pattern introduced

> Read `openapi.md` for full Swagger module setup, theming, CI validation, and Postman export.
> Read `sdk-generation.md` for TypeScript SDK generation, publishing, and frontend integration.
