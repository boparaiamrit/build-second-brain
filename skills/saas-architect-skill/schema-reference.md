# Schema Reference — All Core Drizzle Table Definitions

> Read this file when designing or modifying database schemas.

---

## Table of Contents
1. [Drizzle Setup](#drizzle-setup)
2. [Companies](#companies)
3. [Workspaces](#workspaces)
4. [Domains](#domains)
5. [Recipients (Core)](#recipients-core)
6. [Product Extension Tables](#product-extension-tables)
7. [Custom Field Definitions](#custom-field-definitions)
8. [TimescaleDB Event Hypertables](#timescaledb-event-hypertables)
9. [Audit Logs](#audit-logs)
10. [Job Logs](#job-logs)
11. [Import / Staging](#import--staging)
12. [SSO Connections](#sso-connections)
13. [Admin & Impersonation](#admin--impersonation)

---

## Drizzle Setup

```typescript
// drizzle.config.ts
import { defineConfig } from 'drizzle-kit';
export default defineConfig({
  schema: './src/db/schema/index.ts',
  out: './drizzle/migrations',
  dialect: 'postgresql',
  dbCredentials: { url: process.env.DATABASE_URL! },
});

// src/db/index.ts
import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import * as schema from './schema';
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
export const db = drizzle(pool, { schema });
export type DB = typeof db;

// src/db/db.module.ts — Global provider
import { Global, Module } from '@nestjs/common';
import { db } from './index';
export const DB_TOKEN = 'DRIZZLE_DB';
@Global()
@Module({
  providers: [{ provide: DB_TOKEN, useValue: db }],
  exports: [DB_TOKEN],
})
export class DbModule {}
```

---

## Companies

```typescript
export const companies = pgTable('companies', {
  id: uuid('id').defaultRandom().primaryKey(),
  name: text('name').notNull(),
  slug: text('slug').notNull().unique(),
  subscriptionTier: text('subscription_tier', {
    enum: ['free', 'pro', 'business', 'enterprise'],
  }).notNull().default('free'),
  subscriptionStatus: text('subscription_status', {
    enum: ['active', 'past_due', 'cancelled', 'trialing'],
  }).notNull().default('trialing'),
  seatsLimit: integer('seats_limit').notNull().default(5),
  recipientLimit: integer('recipient_limit').notNull().default(1000),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});
```

---

## Workspaces

```typescript
export const workspaces = pgTable('workspaces', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id').notNull().references(() => companies.id),
  name: text('name').notNull(),
  slug: text('slug').notNull(),
  settings: jsonb('settings').$type<Record<string, unknown>>().default({}),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  companyIdx: index('idx_workspaces_company').on(table.companyId),
  slugUnique: uniqueIndex('idx_workspaces_company_slug').on(table.companyId, table.slug),
}));
```

---

## Domains

```typescript
export const domains = pgTable('domains', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id').notNull().references(() => companies.id),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id),
  domainName: text('domain_name').notNull(),
  verified: boolean('verified').notNull().default(false),
  dnsRecords: jsonb('dns_records').$type<Record<string, unknown>>().default({}),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  workspaceIdx: index('idx_domains_workspace').on(table.workspaceId),
  companyIdx: index('idx_domains_company').on(table.companyId),
  domainUnique: uniqueIndex('idx_domains_workspace_name').on(table.workspaceId, table.domainName),
}));
```

---

## Recipients (Core)

```typescript
export const recipients = pgTable('recipients', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id').notNull().references(() => companies.id),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id),
  domainId: uuid('domain_id').notNull().references(() => domains.id),
  email: text('email').notNull(),
  name: text('name'),
  status: text('status', {
    enum: ['active', 'inactive', 'bounced', 'complained', 'unsubscribed'],
  }).notNull().default('active'),
  customFields: jsonb('custom_fields').$type<Record<string, unknown>>().default({}),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_recipients_domain').on(table.domainId),
  domainEmailUnique: uniqueIndex('idx_recipients_domain_email').on(table.domainId, table.email),
  customFieldsGin: index('idx_recipients_custom_fields').using('gin', table.customFields),
  // Add when proven query pattern exists:
  // workspaceStatusIdx: index('idx_recipients_ws_status').on(table.workspaceId, table.status),
  // companyIdx: index('idx_recipients_company').on(table.companyId),
}));
```

---

## Product Extension Tables

Each product extends the core recipient with its own table.
Creating an extension row = "enrolling" the recipient in that product.

```typescript
// Email Marketing
export const emailRecipients = pgTable('email_recipients', {
  id: uuid('id').defaultRandom().primaryKey(),
  recipientId: uuid('recipient_id').notNull().references(() => recipients.id, { onDelete: 'cascade' }),
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  domainId: uuid('domain_id').notNull(),
  subscriptionStatus: text('subscription_status', {
    enum: ['subscribed', 'unsubscribed', 'cleaned', 'pending'],
  }).notNull().default('subscribed'),
  bounceCount: integer('bounce_count').notNull().default(0),
  lastSentAt: timestamp('last_sent_at'),
  lastOpenedAt: timestamp('last_opened_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_email_recip_domain').on(table.domainId),
  recipientIdx: index('idx_email_recip_recipient').on(table.recipientId),
}));

// SMS
export const smsRecipients = pgTable('sms_recipients', {
  id: uuid('id').defaultRandom().primaryKey(),
  recipientId: uuid('recipient_id').notNull().references(() => recipients.id, { onDelete: 'cascade' }),
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  domainId: uuid('domain_id').notNull(),
  phone: text('phone').notNull(),
  carrier: text('carrier'),
  optInStatus: text('opt_in_status', {
    enum: ['opted_in', 'opted_out', 'pending'],
  }).notNull().default('pending'),
  lastSentAt: timestamp('last_sent_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_sms_recip_domain').on(table.domainId),
  recipientIdx: index('idx_sms_recip_recipient').on(table.recipientId),
  domainPhoneUnique: uniqueIndex('idx_sms_recip_domain_phone').on(table.domainId, table.phone),
}));

// WhatsApp
export const whatsappRecipients = pgTable('whatsapp_recipients', {
  id: uuid('id').defaultRandom().primaryKey(),
  recipientId: uuid('recipient_id').notNull().references(() => recipients.id, { onDelete: 'cascade' }),
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  domainId: uuid('domain_id').notNull(),
  whatsappId: text('whatsapp_id').notNull(),
  optInStatus: text('opt_in_status').notNull().default('pending'),
  templateLanguage: text('template_language').default('en'),
  lastSentAt: timestamp('last_sent_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_wa_recip_domain').on(table.domainId),
  recipientIdx: index('idx_wa_recip_recipient').on(table.recipientId),
}));

// Push Notifications
export const pushRecipients = pgTable('push_recipients', {
  id: uuid('id').defaultRandom().primaryKey(),
  recipientId: uuid('recipient_id').notNull().references(() => recipients.id, { onDelete: 'cascade' }),
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  domainId: uuid('domain_id').notNull(),
  deviceToken: text('device_token').notNull(),
  platform: text('platform', { enum: ['ios', 'android', 'web'] }).notNull(),
  appId: text('app_id').notNull(),
  isActive: boolean('is_active').notNull().default(true),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  domainIdx: index('idx_push_recip_domain').on(table.domainId),
  recipientIdx: index('idx_push_recip_recipient').on(table.recipientId),
  tokenUnique: uniqueIndex('idx_push_recip_token').on(table.deviceToken, table.appId),
}));

// Template for adding new product extensions:
// 1. Create table with: recipientId (FK), companyId, workspaceId, domainId
// 2. Add domain index + recipient index
// 3. Add product-specific columns
// 4. Creating a row = enrolling recipient in this product
```

---

## Custom Field Definitions

Scoped per workspace (all domains in a workspace share the same field schema).

```typescript
export const customFieldDefinitions = pgTable('custom_field_definitions', {
  id: uuid('id').defaultRandom().primaryKey(),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),
  fieldKey: text('field_key').notNull(),
  fieldLabel: text('field_label').notNull(),
  fieldType: text('field_type', {
    enum: ['text', 'number', 'date', 'select', 'multi_select', 'boolean', 'url', 'email'],
  }).notNull(),
  options: jsonb('options').$type<string[]>(),
  isRequired: boolean('is_required').notNull().default(false),
  isFilterable: boolean('is_filterable').notNull().default(true),
  sortOrder: integer('sort_order').notNull().default(0),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  workspaceIdx: index('idx_cfd_workspace').on(table.workspaceId),
  workspaceKeyUnique: uniqueIndex('idx_cfd_workspace_key').on(table.workspaceId, table.fieldKey),
}));

// Cache: Redis key `workspace:{workspaceId}:custom_field_defs` TTL 1hr
// Invalidate on any create/update/delete of definitions
```

---

## TimescaleDB Event Hypertables

```sql
-- Email events
CREATE TABLE email_events (
  time         TIMESTAMPTZ NOT NULL,
  id           UUID DEFAULT gen_random_uuid(),
  recipient_id UUID NOT NULL,
  domain_id    UUID NOT NULL,
  workspace_id UUID NOT NULL,
  company_id   UUID NOT NULL,
  campaign_id  UUID,
  event_type   TEXT NOT NULL,  -- sent, delivered, opened, clicked, bounced, complained
  metadata     JSONB DEFAULT '{}',
  PRIMARY KEY (time, id)
);
SELECT create_hypertable('email_events', 'time', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_email_events_domain ON email_events (domain_id, time DESC);
CREATE INDEX idx_email_events_campaign ON email_events (campaign_id, time DESC);
CREATE INDEX idx_email_events_company ON email_events (company_id, time DESC);
SELECT add_retention_policy('email_events', INTERVAL '90 days');

-- Daily stats (continuous aggregate)
CREATE MATERIALIZED VIEW email_daily_stats
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', time) AS day,
  domain_id, workspace_id, company_id, event_type,
  COUNT(*) as event_count
FROM email_events
GROUP BY day, domain_id, workspace_id, company_id, event_type;

SELECT add_continuous_aggregate_policy('email_daily_stats',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');

-- Replicate pattern for: sms_events, push_events, webhook_events, api_usage_events
```

---

## Audit Logs

```typescript
export const auditLogs = pgTable('audit_logs', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id'),
  workspaceId: uuid('workspace_id'),
  domainId: uuid('domain_id'),
  actorId: uuid('actor_id'),
  actorType: text('actor_type', {
    enum: ['user', 'system', 'admin', 'admin_impersonation', 'api_key'],
  }),
  actorEmail: text('actor_email'),  // denormalized — survives user deletion
  action: text('action').notNull(), // e.g. 'recipient.created', 'sso.authorized'
  resourceType: text('resource_type'),
  resourceId: text('resource_id'),
  metadata: jsonb('metadata').$type<Record<string, unknown>>(),
  ipAddress: text('ip_address'),
  userAgent: text('user_agent'),
  status: text('status', { enum: ['success', 'failure'] }).default('success'),
  errorMessage: text('error_message'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  workspaceCreatedIdx: index('idx_audit_ws_created').on(table.workspaceId, table.createdAt),
  companyCreatedIdx: index('idx_audit_company_created').on(table.companyId, table.createdAt),
  actorIdx: index('idx_audit_actor').on(table.actorId, table.createdAt),
  actionIdx: index('idx_audit_action').on(table.action, table.createdAt),
}));
```

---

## Job Logs

```typescript
export const jobLogs = pgTable('job_logs', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id'),
  workspaceId: uuid('workspace_id'),
  domainId: uuid('domain_id'),
  queueName: text('queue_name').notNull(),
  jobName: text('job_name').notNull(),
  jobId: text('job_id').notNull(),
  payload: jsonb('payload').$type<Record<string, unknown>>(),
  status: text('status', { enum: ['completed', 'failed', 'stalled'] }).notNull(),
  attempts: integer('attempts').default(0),
  maxAttempts: integer('max_attempts').default(3),
  error: text('error'),
  stackTrace: text('stack_trace'),
  startedAt: timestamp('started_at'),
  completedAt: timestamp('completed_at'),
  durationMs: integer('duration_ms'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  workspaceIdx: index('idx_joblogs_ws').on(table.workspaceId, table.createdAt),
  statusIdx: index('idx_joblogs_status').on(table.status, table.createdAt),
}));
```

---

## Import / Staging

```typescript
export const importJobs = pgTable('import_jobs', {
  id: uuid('id').defaultRandom().primaryKey(),
  companyId: uuid('company_id').notNull(),
  workspaceId: uuid('workspace_id').notNull(),
  domainId: uuid('domain_id').notNull(),
  createdBy: uuid('created_by').notNull(),
  status: text('status', {
    enum: ['pending', 'validating', 'preview', 'processing', 'done', 'failed'],
  }).default('pending').notNull(),
  fileUrl: text('file_url'),
  totalRows: integer('total_rows'),
  validRows: integer('valid_rows'),
  errorRows: integer('error_rows'),
  processedRows: integer('processed_rows').default(0),
  validationErrors: jsonb('validation_errors').$type<Array<{ row: number; field: string; message: string }>>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  completedAt: timestamp('completed_at'),
}, (table) => ({
  domainIdx: index('idx_imports_domain').on(table.domainId),
}));

export const importStagingRows = pgTable('import_staging_rows', {
  id: uuid('id').defaultRandom().primaryKey(),
  importJobId: uuid('import_job_id').notNull().references(() => importJobs.id, { onDelete: 'cascade' }),
  domainId: uuid('domain_id').notNull(),
  rowIndex: integer('row_index').notNull(),
  rawData: jsonb('raw_data').notNull().$type<Record<string, unknown>>(),
  mappedData: jsonb('mapped_data').$type<Record<string, unknown>>(),
  status: text('status', { enum: ['pending', 'valid', 'error'] }).default('pending'),
  errors: jsonb('errors').$type<Array<{ field: string; message: string }>>(),
}, (table) => ({
  jobIdx: index('idx_staging_job').on(table.importJobId, table.status),
}));
```

---

## SSO Connections

```typescript
export const ssoConnections = pgTable('sso_connections', {
  id: uuid('id').defaultRandom().primaryKey(),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id),
  provider: text('provider', {
    enum: ['microsoft_ad', 'google', 'okta', 'saml'],
  }).notNull(),
  clientId: text('client_id'),
  clientSecret: text('client_secret'),     // encrypted at rest
  tenantId: text('tenant_id'),             // Microsoft AD
  domain: text('domain'),                  // Google Workspace
  metadataUrl: text('metadata_url'),       // SAML
  config: jsonb('config').$type<Record<string, unknown>>(),
  accessToken: text('access_token'),       // encrypted
  refreshToken: text('refresh_token'),     // encrypted
  tokenExpiresAt: timestamp('token_expires_at'),
  isActive: boolean('is_active').default(false),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  workspaceIdx: index('idx_sso_workspace').on(table.workspaceId),
}));
```

---

## Admin & Impersonation

```typescript
export const adminUsers = pgTable('admin_users', {
  id: uuid('id').defaultRandom().primaryKey(),
  email: text('email').notNull().unique(),
  passwordHash: text('password_hash').notNull(),
  role: text('role', { enum: ['admin', 'super_admin', 'support'] }).default('admin'),
  isActive: boolean('is_active').default(true),
  mfaSecret: text('mfa_secret'),  // TOTP, encrypted
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const impersonationSessions = pgTable('impersonation_sessions', {
  id: uuid('id').defaultRandom().primaryKey(),
  adminId: uuid('admin_id').notNull().references(() => adminUsers.id),
  workspaceId: uuid('workspace_id').notNull().references(() => workspaces.id),
  impersonatedUserId: uuid('impersonated_user_id'),
  reason: text('reason').notNull(),          // REQUIRED — stored permanently
  sessionToken: text('session_token').notNull().unique(),
  expiresAt: timestamp('expires_at').notNull(), // max 1 hour, non-renewable
  endedAt: timestamp('ended_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});
```
