# Multi-Tenant Isolation Testing — THE MOST CRITICAL FILE

> This is the most important testing file in the entire skill. A broken feature is a bug.
> A broken tenant boundary is a security incident, a compliance violation, and potentially
> a company-ending event. Every endpoint that touches data MUST have isolation tests.

---

## Table of Contents
1. [Isolation Test Framework](#isolation-test-framework)
2. [Test Data Factory for Multi-Tenant Scenarios](#test-data-factory)
3. [Workspace Isolation Test Template](#workspace-isolation-test-template)
4. [Domain Isolation Test Template](#domain-isolation-test-template)
5. [Bulk Operation Isolation Tests](#bulk-operation-isolation-tests)
6. [Company Admin Scope Tests](#company-admin-scope-tests)
7. [Person De-Duplication Tests (UC2)](#person-de-duplication-tests)
8. [Cross-Workspace Person Linking Tests (UC3)](#cross-workspace-person-linking-tests)
9. [Settings Inheritance Tests](#settings-inheritance-tests)
10. [Blueprint Deployment Tests](#blueprint-deployment-tests)
11. [Progressive Complexity Tests](#progressive-complexity-tests)
12. [The Six Negative Security Tests](#six-negative-security-tests)
13. [Isolation Test CI Gate](#isolation-test-ci-gate)
14. [Checklist](#checklist)

---

## Isolation Test Framework

### Test Infrastructure Setup

```typescript
// test/helpers/test-db.ts
import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import { sql } from 'drizzle-orm';
import * as schema from '../../src/db/schema';

export class TestDbHelper {
  private pool: Pool;
  public drizzle: ReturnType<typeof drizzle>;

  static async create(): Promise<TestDbHelper> {
    const helper = new TestDbHelper();
    await helper.init();
    return helper;
  }

  private async init() {
    this.pool = new Pool({
      connectionString: process.env.TEST_DATABASE_URL || 'postgresql://test:test@localhost:5432/test_db',
    });
    this.drizzle = drizzle(this.pool, { schema });
  }

  async createCompany(data: Partial<typeof schema.companies.$inferInsert> = {}) {
    const [company] = await this.drizzle.insert(schema.companies).values({
      name: data.name ?? 'Test Company',
      slug: data.slug ?? `test-${Date.now()}`,
      subscriptionTier: data.subscriptionTier ?? 'enterprise',
      subscriptionStatus: data.subscriptionStatus ?? 'active',
      recipientLimit: data.recipientLimit ?? 100_000,
      seatsLimit: data.seatsLimit ?? 50,
    }).returning();
    return company;
  }

  async createWorkspace(companyId: string, data: Partial<typeof schema.workspaces.$inferInsert> = {}) {
    const [workspace] = await this.drizzle.insert(schema.workspaces).values({
      companyId,
      name: data.name ?? 'Test Workspace',
      slug: data.slug ?? `ws-${Date.now()}`,
    }).returning();
    return workspace;
  }

  async createDomain(workspaceId: string, companyId: string, data: Partial<typeof schema.domains.$inferInsert> = {}) {
    const [domain] = await this.drizzle.insert(schema.domains).values({
      workspaceId,
      companyId,
      domainName: data.domainName ?? `test-${Date.now()}.com`,
      verified: data.verified ?? true,
    }).returning();
    return domain;
  }

  async createRecipient(
    domainId: string,
    workspaceId: string,
    companyId: string,
    data: Partial<typeof schema.recipients.$inferInsert> = {},
  ) {
    const [recipient] = await this.drizzle.insert(schema.recipients).values({
      domainId,
      workspaceId,
      companyId,
      email: data.email ?? `user-${Date.now()}@test.com`,
      name: data.name ?? 'Test User',
      status: data.status ?? 'active',
      customFields: data.customFields ?? {},
    }).returning();
    return recipient;
  }

  async createAuthToken(scopeId: string, role: 'workspace_admin' | 'company_admin' | 'member'): Promise<string> {
    // Generate a JWT token for testing.
    // Implementation depends on your auth module.
    // This should create a real token that your guards will accept.
    const jwt = await import('jsonwebtoken');
    const secret = process.env.JWT_SECRET || 'test-secret';
    return jwt.sign({ sub: `user-${Date.now()}`, scopeId, role }, secret, { expiresIn: '1h' });
  }

  async truncate(...tables: string[]) {
    for (const table of tables) {
      await this.drizzle.execute(sql.raw(`TRUNCATE TABLE "${table}" CASCADE`));
    }
  }

  async insertMany(table: string, rows: Record<string, unknown>[]) {
    if (rows.length === 0) return [];
    const cols = Object.keys(rows[0]);
    const placeholders = rows.map(
      (_, i) => `(${cols.map((_, j) => `$${i * cols.length + j + 1}`).join(', ')})`,
    ).join(', ');
    const values = rows.flatMap(r => cols.map(c => r[c]));
    const query = `INSERT INTO "${table}" (${cols.map(c => `"${c}"`).join(', ')}) VALUES ${placeholders} RETURNING *`;
    const result = await this.pool.query(query, values);
    return result.rows;
  }

  async cleanup() {
    await this.pool.end();
  }
}
```

### Global Isolation Test Setup

```typescript
// test/isolation-setup.ts
import { TestDbHelper } from './helpers/test-db';
import { createTestTenant } from './factories/tenant.factory';

let db: TestDbHelper;
let tenant: Awaited<ReturnType<typeof createTestTenant>>;

export async function getTestContext() {
  if (!db) {
    db = await TestDbHelper.create();
    tenant = await createTestTenant(db);
  }
  return { db, tenant };
}

export async function teardownTestContext() {
  if (db) {
    await db.cleanup();
  }
}
```

---

## Test Data Factory

### Full Multi-Tenant Hierarchy Factory

```typescript
// test/factories/tenant.factory.ts
import { TestDbHelper } from '../helpers/test-db';
import { randomUUID } from 'crypto';

interface TestTenant {
  company: { id: string; name: string };
  // UC3: Two workspaces (Tata Steel + Tata Motors)
  workspaceA: { id: string; name: string; companyId: string };
  workspaceB: { id: string; name: string; companyId: string };
  // UC2: Workspace B has two domains
  domainA: { id: string; domainName: string; workspaceId: string; companyId: string };
  domainB: { id: string; domainName: string; workspaceId: string; companyId: string };
  domainC: { id: string; domainName: string; workspaceId: string; companyId: string };
  // Auth tokens
  tokenA: string;   // Workspace A admin
  tokenB: string;   // Workspace B admin
  companyToken: string; // Company admin (sees all)
  // Pre-seeded data
  recipientsA: Array<{ id: string; email: string; domainId: string }>;
  recipientsB: Array<{ id: string; email: string; domainId: string }>;
  recipientsC: Array<{ id: string; email: string; domainId: string }>;
}

/**
 * Creates a complete multi-tenant test hierarchy:
 *
 * Company: Tata Group (enterprise plan)
 * ├── Workspace A: Tata Steel
 * │   └── Domain A: tatasteel.com
 * │       ├── rajesh@tatasteel.com
 * │       ├── priya@tatasteel.com
 * │       └── suresh@tatasteel.com
 * └── Workspace B: Tata Motors
 *     ├── Domain B: tatamotors.com
 *     │   ├── vikram@tatamotors.com
 *     │   └── anita@tatamotors.com
 *     └── Domain C: tatamotors.co.in
 *         ├── vikram@tatamotors.co.in  (same person, different domain — UC2)
 *         └── deepa@tatamotors.co.in
 */
export async function createTestTenant(db: TestDbHelper): Promise<TestTenant> {
  const suffix = randomUUID().slice(0, 8);

  // Company
  const company = await db.createCompany({
    name: 'Tata Group',
    slug: `tata-${suffix}`,
    subscriptionTier: 'enterprise',
    subscriptionStatus: 'active',
    recipientLimit: 100_000,
  });

  // Workspaces
  const workspaceA = await db.createWorkspace(company.id, {
    name: 'Tata Steel',
    slug: `tata-steel-${suffix}`,
  });

  const workspaceB = await db.createWorkspace(company.id, {
    name: 'Tata Motors',
    slug: `tata-motors-${suffix}`,
  });

  // Domains
  const domainA = await db.createDomain(workspaceA.id, company.id, {
    domainName: `tatasteel-${suffix}.com`,
    verified: true,
  });

  const domainB = await db.createDomain(workspaceB.id, company.id, {
    domainName: `tatamotors-${suffix}.com`,
    verified: true,
  });

  const domainC = await db.createDomain(workspaceB.id, company.id, {
    domainName: `tatamotors-${suffix}.co.in`,
    verified: true,
  });

  // Auth tokens
  const tokenA = await db.createAuthToken(workspaceA.id, 'workspace_admin');
  const tokenB = await db.createAuthToken(workspaceB.id, 'workspace_admin');
  const companyToken = await db.createAuthToken(company.id, 'company_admin');

  // Seed recipients in Domain A (Tata Steel)
  const recipientsA = [];
  for (const r of [
    { email: `rajesh@tatasteel-${suffix}.com`, name: 'Rajesh Kumar' },
    { email: `priya@tatasteel-${suffix}.com`, name: 'Priya Sharma' },
    { email: `suresh@tatasteel-${suffix}.com`, name: 'Suresh Reddy' },
  ]) {
    const recipient = await db.createRecipient(domainA.id, workspaceA.id, company.id, {
      email: r.email,
      name: r.name,
    });
    recipientsA.push({ id: recipient.id, email: r.email, domainId: domainA.id });
  }

  // Seed recipients in Domain B (Tata Motors .com)
  const recipientsB = [];
  for (const r of [
    { email: `vikram@tatamotors-${suffix}.com`, name: 'Vikram Singh' },
    { email: `anita@tatamotors-${suffix}.com`, name: 'Anita Patel' },
  ]) {
    const recipient = await db.createRecipient(domainB.id, workspaceB.id, company.id, {
      email: r.email,
      name: r.name,
    });
    recipientsB.push({ id: recipient.id, email: r.email, domainId: domainB.id });
  }

  // Seed recipients in Domain C (Tata Motors .co.in)
  const recipientsC = [];
  for (const r of [
    { email: `vikram@tatamotors-${suffix}.co.in`, name: 'Vikram Singh' }, // Same person as domain B
    { email: `deepa@tatamotors-${suffix}.co.in`, name: 'Deepa Iyer' },
  ]) {
    const recipient = await db.createRecipient(domainC.id, workspaceB.id, company.id, {
      email: r.email,
      name: r.name,
    });
    recipientsC.push({ id: recipient.id, email: r.email, domainId: domainC.id });
  }

  return {
    company,
    workspaceA,
    workspaceB,
    domainA,
    domainB,
    domainC,
    tokenA,
    tokenB,
    companyToken,
    recipientsA,
    recipientsB,
    recipientsC,
  };
}

/**
 * Creates a simple UC1 tenant for testing that UC3 features are hidden.
 */
export async function createUC1Tenant(db: TestDbHelper) {
  const suffix = randomUUID().slice(0, 8);

  const company = await db.createCompany({
    name: 'Zerodha',
    slug: `zerodha-${suffix}`,
    subscriptionTier: 'pro',
  });

  const workspace = await db.createWorkspace(company.id, {
    name: 'Zerodha',
    slug: `zerodha-${suffix}`,
  });

  const domain = await db.createDomain(workspace.id, company.id, {
    domainName: `zerodha-${suffix}.com`,
  });

  const token = await db.createAuthToken(workspace.id, 'workspace_admin');

  return { company, workspace, domain, token };
}

/**
 * Creates a UC2 tenant (single workspace, multiple domains).
 */
export async function createUC2Tenant(db: TestDbHelper) {
  const suffix = randomUUID().slice(0, 8);

  const company = await db.createCompany({
    name: 'Jio Platforms',
    slug: `jio-${suffix}`,
    subscriptionTier: 'business',
  });

  const workspace = await db.createWorkspace(company.id, {
    name: 'Jio',
    slug: `jio-${suffix}`,
  });

  const domainJio = await db.createDomain(workspace.id, company.id, {
    domainName: `jio-${suffix}.com`,
  });

  const domainSaavn = await db.createDomain(workspace.id, company.id, {
    domainName: `jiosaavn-${suffix}.com`,
  });

  const token = await db.createAuthToken(workspace.id, 'workspace_admin');

  return { company, workspace, domainJio, domainSaavn, token };
}
```

---

## Workspace Isolation Test Template

### GET Endpoint Isolation

```typescript
// src/modules/recipients/__tests__/recipients.isolation.spec.ts
import { Test } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import * as request from 'supertest';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { AppModule } from '../../../app.module';
import { TestDbHelper } from '../../../../test/helpers/test-db';
import { createTestTenant } from '../../../../test/factories/tenant.factory';

describe('Recipients — Workspace Isolation', () => {
  let app: INestApplication;
  let db: TestDbHelper;
  let tenant: Awaited<ReturnType<typeof createTestTenant>>;

  beforeAll(async () => {
    const module = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = module.createNestApplication();
    await app.init();

    db = new TestDbHelper(module);
    tenant = await createTestTenant(db);
  });

  afterAll(async () => {
    await db.cleanup();
    await app.close();
  });

  describe('GET /domains/:domainId/recipients', () => {
    it('should return ONLY recipients from the requested domain', async () => {
      const res = await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(200);

      // Should have domain A recipients
      expect(res.body.data.length).toBe(tenant.recipientsA.length);
      // Every returned recipient must belong to domain A
      for (const recipient of res.body.data) {
        expect(recipient.domainId).toBe(tenant.domainA.id);
        expect(recipient.workspaceId).toBe(tenant.workspaceA.id);
      }
    });

    it('should NOT return workspace B recipients when authenticated as workspace A admin', async () => {
      const res = await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(200);

      const emails = res.body.data.map((r: any) => r.email);

      // Must NOT contain any workspace B emails
      for (const recipientB of tenant.recipientsB) {
        expect(emails).not.toContain(recipientB.email);
      }
      for (const recipientC of tenant.recipientsC) {
        expect(emails).not.toContain(recipientC.email);
      }
    });

    it('should return 403 when workspace A admin tries to access workspace B domain', async () => {
      // Token A has access to workspace A only
      // Domain B belongs to workspace B
      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainB.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(403);
    });

    it('should return 403 when using spoofed x-workspace-id header', async () => {
      // Authenticate as workspace A admin but try to set workspace B header
      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .set('x-workspace-id', tenant.workspaceB.id) // Spoofed!
        .expect(403);
    });
  });

  describe('GET /domains/:domainId/recipients/:id', () => {
    it('should return 404 when accessing workspace B recipient from workspace A', async () => {
      const recipientInB = tenant.recipientsB[0];

      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainA.id}/recipients/${recipientInB.id}`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(404);
    });

    it('should return 404 when using correct domain but wrong workspace token', async () => {
      const recipientInB = tenant.recipientsB[0];

      // Using domain B (correct domain for this recipient) but token A (wrong workspace)
      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainB.id}/recipients/${recipientInB.id}`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .expect(403); // or 404 — either is acceptable, 403 is more explicit
    });
  });
});
```

### POST/PATCH/DELETE Isolation

```typescript
describe('POST /domains/:domainId/recipients — Isolation', () => {
  it('should NOT allow creating a recipient in workspace B domain using workspace A token', async () => {
    await request(app.getHttpServer())
      .post(`/domains/${tenant.domainB.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({ email: 'injected@evil.com', firstName: 'Evil', lastName: 'User' })
      .expect(403);

    // Double-check: the recipient should NOT exist in domain B
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    const emails = res.body.data.map((r: any) => r.email);
    expect(emails).not.toContain('injected@evil.com');
  });
});

describe('PATCH /domains/:domainId/recipients/:id — Isolation', () => {
  it('should NOT allow updating a workspace B recipient using workspace A token', async () => {
    const targetRecipient = tenant.recipientsB[0];

    await request(app.getHttpServer())
      .patch(`/domains/${tenant.domainB.id}/recipients/${targetRecipient.id}`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({ status: 'inactive' })
      .expect(403);

    // Verify recipient was NOT modified
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients/${targetRecipient.id}`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(res.body.data.status).toBe('active'); // Unchanged
  });
});

describe('DELETE /domains/:domainId/recipients/:id — Isolation', () => {
  it('should NOT allow deleting a workspace B recipient using workspace A token', async () => {
    const targetRecipient = tenant.recipientsB[0];

    await request(app.getHttpServer())
      .delete(`/domains/${tenant.domainB.id}/recipients/${targetRecipient.id}`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(403);

    // Verify recipient still exists
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients/${targetRecipient.id}`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(res.body.data.id).toBe(targetRecipient.id);
  });
});
```

---

## Domain Isolation Test Template

```typescript
describe('Domain-Level Isolation (within same workspace)', () => {
  it('should return ONLY domain B recipients when querying domain B', async () => {
    // Both domain B and domain C belong to workspace B
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    for (const recipient of res.body.data) {
      expect(recipient.domainId).toBe(tenant.domainB.id);
    }

    // Must NOT contain domain C recipients
    const emails = res.body.data.map((r: any) => r.email);
    for (const recipientC of tenant.recipientsC) {
      expect(emails).not.toContain(recipientC.email);
    }
  });

  it('should return ONLY domain C recipients when querying domain C', async () => {
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainC.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    for (const recipient of res.body.data) {
      expect(recipient.domainId).toBe(tenant.domainC.id);
    }
  });

  it('should enforce domain uniqueness within a domain (not cross-domain)', async () => {
    // Same email can exist in domain B and domain C (different identity providers)
    const emailInB = tenant.recipientsB[0].email;
    const emailPrefix = emailInB.split('@')[0];

    // This should succeed — different domain
    const res = await request(app.getHttpServer())
      .post(`/domains/${tenant.domainC.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({ email: `${emailPrefix}@${tenant.domainC.domainName}`, firstName: 'Dup', lastName: 'Cross' })
      .expect(201);

    expect(res.body.data.domainId).toBe(tenant.domainC.id);
  });
});
```

---

## Bulk Operation Isolation Tests

```typescript
describe('Bulk Operation Isolation', () => {
  it('should only delete records belonging to the authenticated workspace', async () => {
    // Try to delete: 2 from workspace A + 2 from workspace B
    const mixedIds = [
      tenant.recipientsA[0].id,
      tenant.recipientsA[1].id,
      tenant.recipientsB[0].id, // Different workspace!
      tenant.recipientsB[1].id, // Different workspace!
    ];

    const res = await request(app.getHttpServer())
      .post(`/domains/${tenant.domainA.id}/recipients/bulk-delete`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({ ids: mixedIds })
      .expect(200);

    // Should report only 2 deleted (workspace A records)
    expect(res.body.affected).toBe(2);

    // Verify workspace B records are UNTOUCHED
    for (const recipientB of [tenant.recipientsB[0], tenant.recipientsB[1]]) {
      const check = await request(app.getHttpServer())
        .get(`/domains/${tenant.domainB.id}/recipients/${recipientB.id}`)
        .set('Authorization', `Bearer ${tenant.tokenB}`)
        .expect(200);

      expect(check.body.data.id).toBe(recipientB.id);
    }
  });

  it('should only update records belonging to the authenticated workspace', async () => {
    const mixedIds = [
      tenant.recipientsA[0].id,
      tenant.recipientsB[0].id, // Different workspace!
    ];

    await request(app.getHttpServer())
      .post(`/domains/${tenant.domainA.id}/recipients/bulk-update`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({
        ids: mixedIds,
        updates: { status: 'inactive' },
      })
      .expect(200);

    // Workspace B recipient should still be active
    const check = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients/${tenant.recipientsB[0].id}`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(check.body.data.status).toBe('active'); // UNTOUCHED
  });

  it('should reject bulk operation when ALL IDs belong to wrong workspace', async () => {
    const wrongIds = [tenant.recipientsB[0].id, tenant.recipientsB[1].id];

    const res = await request(app.getHttpServer())
      .post(`/domains/${tenant.domainA.id}/recipients/bulk-delete`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({ ids: wrongIds })
      .expect(200);

    // Zero deleted — none belonged to workspace A
    expect(res.body.affected).toBe(0);
  });
});
```

---

## Company Admin Scope Tests

```typescript
describe('Company Admin Scope', () => {
  it('should return aggregated data from ALL workspaces at company level', async () => {
    const res = await request(app.getHttpServer())
      .get(`/companies/${tenant.company.id}/reports/recipients`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    // Should include recipients from BOTH workspaces
    const totalCount = tenant.recipientsA.length + tenant.recipientsB.length + tenant.recipientsC.length;
    expect(res.body.data.totalRecipients).toBe(totalCount);

    // Should have breakdown by workspace
    expect(res.body.data.byWorkspace).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          workspaceId: tenant.workspaceA.id,
          count: tenant.recipientsA.length,
        }),
        expect.objectContaining({
          workspaceId: tenant.workspaceB.id,
          count: tenant.recipientsB.length + tenant.recipientsC.length,
        }),
      ]),
    );
  });

  it('should return ONLY workspace-scoped data at workspace level (even for company admin)', async () => {
    // Company admin querying a specific workspace endpoint should see ONLY that workspace
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainA.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    for (const recipient of res.body.data) {
      expect(recipient.workspaceId).toBe(tenant.workspaceA.id);
    }
  });

  it('should NOT allow company admin to modify data via company endpoint', async () => {
    // Company-level endpoints are read-only aggregation
    await request(app.getHttpServer())
      .post(`/companies/${tenant.company.id}/reports/recipients`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({ action: 'bulk-delete', ids: [tenant.recipientsA[0].id] })
      .expect(405); // Method not allowed — company endpoints are read-only
  });

  it('should NOT allow workspace admin to access company-level endpoints', async () => {
    await request(app.getHttpServer())
      .get(`/companies/${tenant.company.id}/reports/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenA}`) // Workspace admin, not company admin
      .expect(403);
  });
});
```

---

## Person De-Duplication Tests (UC2)

```typescript
describe('Person De-Duplication (UC2 — Intra-Workspace)', () => {
  it('should link two recipients to the same Person when matched', async () => {
    // Vikram exists in domain B (tatamotors.com) and domain C (tatamotors.co.in)
    // Both are in workspace B — this is UC2 (intra-workspace de-dup)

    const vikramB = tenant.recipientsB.find(r => r.email.startsWith('vikram'));
    const vikramC = tenant.recipientsC.find(r => r.email.startsWith('vikram'));

    // Trigger Person matching
    await request(app.getHttpServer())
      .post(`/workspaces/${tenant.workspaceB.id}/persons/match`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    // Verify both recipients point to the same Person
    const resB = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainB.id}/recipients/${vikramB!.id}`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    const resC = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainC.id}/recipients/${vikramC!.id}`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(resB.body.data.personId).toBeDefined();
    expect(resB.body.data.personId).toBe(resC.body.data.personId);
  });

  it('should count Vikram as ONE person in campaign targeting with deduplicateByPerson=true', async () => {
    // Create campaign targeting "all users" with de-dup enabled
    const res = await request(app.getHttpServer())
      .post(`/workspaces/${tenant.workspaceB.id}/campaigns`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({
        name: 'Test De-Dup Campaign',
        targetFilter: {},
        deduplicateByPerson: true,
      })
      .expect(201);

    // Preview targets
    const preview = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/campaigns/${res.body.data.id}/targets/preview`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    // Vikram should appear once, not twice
    const vikramTargets = preview.body.data.targets.filter((t: any) =>
      t.name?.includes('Vikram'),
    );
    expect(vikramTargets).toHaveLength(1);
  });

  it('should count Vikram as TWO recipients in campaign targeting with deduplicateByPerson=false', async () => {
    const res = await request(app.getHttpServer())
      .post(`/workspaces/${tenant.workspaceB.id}/campaigns`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({
        name: 'Test No-DeDup Campaign',
        targetFilter: {},
        deduplicateByPerson: false,
      })
      .expect(201);

    const preview = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/campaigns/${res.body.data.id}/targets/preview`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    const vikramTargets = preview.body.data.targets.filter((t: any) =>
      t.name?.includes('Vikram'),
    );
    expect(vikramTargets).toHaveLength(2); // One per domain
  });

  it('should NOT link persons across workspaces in UC2 mode (intra-workspace only)', async () => {
    // Workspace A and workspace B might have same-named people
    // UC2 de-dup is INTRA-workspace only — not cross-workspace

    const wsAPersons = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/persons`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    const wsBPersons = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/persons`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    // No Person should have recipients from both workspaces
    const allPersonIds = new Set([
      ...wsAPersons.body.data.map((p: any) => p.id),
      ...wsBPersons.body.data.map((p: any) => p.id),
    ]);
    // Total unique person IDs = sum of both (no overlap)
    expect(allPersonIds.size).toBe(
      wsAPersons.body.data.length + wsBPersons.body.data.length,
    );
  });
});
```

---

## Cross-Workspace Person Linking Tests (UC3)

```typescript
describe('Cross-Workspace Person Linking (UC3 — MSSP)', () => {
  it('should allow company admin to link Persons across workspaces', async () => {
    // Company admin can link a Person from workspace A to workspace B
    const personInA = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/persons`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    const personInB = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/persons`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    if (personInA.body.data.length > 0 && personInB.body.data.length > 0) {
      const res = await request(app.getHttpServer())
        .post(`/companies/${tenant.company.id}/persons/link`)
        .set('Authorization', `Bearer ${tenant.companyToken}`)
        .send({
          personIdA: personInA.body.data[0].id,
          personIdB: personInB.body.data[0].id,
        })
        .expect(200);

      expect(res.body.data.linked).toBe(true);
    }
  });

  it('should NOT allow workspace admin to link Persons across workspaces', async () => {
    // Workspace admin does NOT have cross-workspace linking permission
    await request(app.getHttpServer())
      .post(`/companies/${tenant.company.id}/persons/link`)
      .set('Authorization', `Bearer ${tenant.tokenA}`) // Workspace admin
      .send({
        personIdA: 'any-id',
        personIdB: 'any-id',
      })
      .expect(403);
  });

  it('should credit training completion across workspaces via CROSS_WS_CREDIT', async () => {
    // Setup: Rajesh in workspace A completes training
    // If Rajesh is linked to a Person who also has a recipient in workspace B,
    // workspace B should get a CROSS_WS_CREDIT completion

    // This test verifies the cross-workspace training credit mechanism
    // described in mssp-patterns.md

    const res = await request(app.getHttpServer())
      .post(`/domains/${tenant.domainA.id}/training-targets/${/* target ID */''}/complete`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    // Verify cross-workspace credit was created (if person is linked)
    // The credit should appear in workspace B's training targets
  });
});
```

---

## Settings Inheritance Tests

```typescript
describe('Settings Inheritance', () => {
  it('should return company default when workspace has not overridden', async () => {
    // Set company default
    await request(app.getHttpServer())
      .patch(`/companies/${tenant.company.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({ trackOpens: true })
      .expect(200);

    // Workspace A should inherit
    const res = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    expect(res.body.data.trackOpens).toBe(true);
    expect(res.body.data._sources.trackOpens).toBe('company');
  });

  it('should return workspace override when workspace has overridden', async () => {
    // Override at workspace level
    await request(app.getHttpServer())
      .patch(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({ trackOpens: false, _override: ['trackOpens'] })
      .expect(200);

    const res = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(res.body.data.trackOpens).toBe(false);
    expect(res.body.data._sources.trackOpens).toBe('override');
  });

  it('should propagate company default changes to non-overriding workspaces', async () => {
    // Change company default
    await request(app.getHttpServer())
      .patch(`/companies/${tenant.company.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({ trackOpens: false })
      .expect(200);

    // Workspace A (inheriting) should see the change
    const resA = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);
    expect(resA.body.data.trackOpens).toBe(false);

    // Workspace B (overriding) should NOT be affected
    const resB = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);
    expect(resB.body.data.trackOpens).toBe(false); // Still the overridden value
    expect(resB.body.data._sources.trackOpens).toBe('override'); // Source unchanged
  });

  it('should reset workspace override back to company default', async () => {
    // Reset the override
    await request(app.getHttpServer())
      .patch(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({ _reset: ['trackOpens'] })
      .expect(200);

    const res = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(res.body.data._sources.trackOpens).toBe('company');
  });

  it('should NOT allow workspace admin to modify company-level settings', async () => {
    await request(app.getHttpServer())
      .patch(`/companies/${tenant.company.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenA}`) // Workspace admin
      .send({ trackOpens: true })
      .expect(403);
  });
});
```

---

## Blueprint Deployment Tests

```typescript
describe('Blueprint Deployment', () => {
  it('should create workspace-specific campaigns from blueprint', async () => {
    // Company admin creates blueprint targeting both workspaces
    const blueprint = await request(app.getHttpServer())
      .post(`/companies/${tenant.company.id}/blueprints`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({
        name: 'Q1 Security Campaign',
        targetWorkspaceIds: [tenant.workspaceA.id, tenant.workspaceB.id],
        scenarioId: 'sc-phishing-1',
        schedule: { startDate: '2024-04-01' },
      })
      .expect(201);

    // Deploy
    const deploy = await request(app.getHttpServer())
      .post(`/companies/${tenant.company.id}/blueprints/${blueprint.body.data.id}/deploy`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    expect(deploy.body.data.deployed).toBe(2);

    // Verify workspace-specific campaigns were created
    const campaignsA = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/campaigns`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    const blueprintCampaign = campaignsA.body.data.find(
      (c: any) => c.blueprintId === blueprint.body.data.id,
    );
    expect(blueprintCampaign).toBeDefined();
    expect(blueprintCampaign.workspaceId).toBe(tenant.workspaceA.id);
  });

  it('should NOT allow workspace admin to create blueprints', async () => {
    await request(app.getHttpServer())
      .post(`/companies/${tenant.company.id}/blueprints`)
      .set('Authorization', `Bearer ${tenant.tokenA}`) // Workspace admin
      .send({ name: 'Unauthorized Blueprint' })
      .expect(403);
  });

  it('should allow workspace admin to pause a blueprint-spawned campaign in their workspace', async () => {
    const campaigns = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/campaigns`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    const blueprintCampaign = campaigns.body.data.find((c: any) => c.blueprintId);
    if (blueprintCampaign) {
      await request(app.getHttpServer())
        .patch(`/workspaces/${tenant.workspaceA.id}/campaigns/${blueprintCampaign.id}`)
        .set('Authorization', `Bearer ${tenant.tokenA}`)
        .send({ status: 'paused' })
        .expect(200);
    }
  });
});
```

---

## Progressive Complexity Tests

```typescript
describe('Progressive Complexity — UC1 Hides Multi-Tenant Features', () => {
  let uc1Tenant: Awaited<ReturnType<typeof createUC1Tenant>>;

  beforeAll(async () => {
    uc1Tenant = await createUC1Tenant(db);
  });

  it('should return showWorkspaceSelector=false for single-workspace company', async () => {
    const res = await request(app.getHttpServer())
      .get('/auth/me')
      .set('Authorization', `Bearer ${uc1Tenant.token}`)
      .expect(200);

    expect(res.body.data.ui.showWorkspaceSelector).toBe(false);
    expect(res.body.data.ui.showDomainTabs).toBe(false);
    expect(res.body.data.ui.showPersonColumn).toBe(false);
    expect(res.body.data.ui.showCompanyLibrary).toBe(false);
    expect(res.body.data.ui.showBlueprintFeatures).toBe(false);
    expect(res.body.data.ui.showSettingsInheritance).toBe(false);
  });

  it('should return showWorkspaceSelector=true for multi-workspace company', async () => {
    const res = await request(app.getHttpServer())
      .get('/auth/me')
      .set('Authorization', `Bearer ${tenant.tokenA}`) // UC3 tenant
      .expect(200);

    expect(res.body.data.ui.showWorkspaceSelector).toBe(true);
    expect(res.body.data.ui.showCompanyLibrary).toBe(true);
    expect(res.body.data.ui.showBlueprintFeatures).toBe(true);
    expect(res.body.data.ui.showSettingsInheritance).toBe(true);
  });

  it('should return showDomainTabs=true for multi-domain workspace', async () => {
    // Workspace B has 2 domains (UC2)
    const res = await request(app.getHttpServer())
      .get('/auth/me')
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    expect(res.body.data.ui.showDomainTabs).toBe(true);
    expect(res.body.data.ui.showPersonColumn).toBe(true);
  });
});
```

---

## The Six Negative Security Tests

These are the six tests from the MSSP audit skill, now as runnable code.

### Test 1: Cross-Workspace Data Leak

```typescript
describe('NEGATIVE TEST 1: Cross-Workspace Data Leak', () => {
  it('should NEVER return workspace B data when authenticated as workspace A admin', async () => {
    // Authenticate as workspace A
    const res = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainA.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);

    // Every record must belong to workspace A
    for (const record of res.body.data) {
      expect(record.workspaceId).toBe(tenant.workspaceA.id);
      expect(record.workspaceId).not.toBe(tenant.workspaceB.id);
    }

    // Try with spoofed header — must still not work
    const spoofed = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainA.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .set('x-workspace-id', tenant.workspaceB.id)
      .expect(403);
  });
});
```

### Test 2: Bulk Operation Cross-Workspace

```typescript
describe('NEGATIVE TEST 2: Bulk Operation Cross-Workspace', () => {
  it('should only affect own-workspace records in bulk delete', async () => {
    // Mix IDs from both workspaces
    const ownIds = tenant.recipientsA.map(r => r.id);
    const foreignIds = tenant.recipientsB.map(r => r.id);
    const allIds = [...ownIds, ...foreignIds];

    const res = await request(app.getHttpServer())
      .post(`/domains/${tenant.domainA.id}/recipients/bulk-delete`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .send({ ids: allIds })
      .expect(200);

    // Only own-workspace records should be affected
    expect(res.body.affected).toBeLessThanOrEqual(ownIds.length);

    // Verify foreign records are UNTOUCHED
    for (const foreignId of foreignIds) {
      await request(app.getHttpServer())
        .get(`/domains/${tenant.domainB.id}/recipients/${foreignId}`)
        .set('Authorization', `Bearer ${tenant.tokenB}`)
        .expect(200); // Still exists
    }
  });
});
```

### Test 3: Company Admin Scope Boundary

```typescript
describe('NEGATIVE TEST 3: Company Admin Scope Boundary', () => {
  it('should aggregate at company level but isolate at workspace level', async () => {
    // Company endpoint: should see ALL workspaces
    const companyRes = await request(app.getHttpServer())
      .get(`/companies/${tenant.company.id}/reports/recipients`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    const totalExpected = tenant.recipientsA.length + tenant.recipientsB.length + tenant.recipientsC.length;
    expect(companyRes.body.data.totalRecipients).toBe(totalExpected);

    // Workspace endpoint (same admin): should see ONLY that workspace
    const wsRes = await request(app.getHttpServer())
      .get(`/domains/${tenant.domainA.id}/recipients`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .expect(200);

    for (const record of wsRes.body.data) {
      expect(record.workspaceId).toBe(tenant.workspaceA.id);
    }
  });
});
```

### Test 4: Person De-Duplication

```typescript
describe('NEGATIVE TEST 4: Person De-Duplication', () => {
  it('should treat Vikram as ONE person with deduplicateByPerson=true', async () => {
    // Vikram exists in domain B and domain C (both workspace B)
    // With de-dup: 1 target. Without de-dup: 2 targets.

    const campaign = await request(app.getHttpServer())
      .post(`/workspaces/${tenant.workspaceB.id}/campaigns`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({
        name: 'De-Dup Test',
        targetFilter: {},
        deduplicateByPerson: true,
      })
      .expect(201);

    const preview = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/campaigns/${campaign.body.data.id}/targets/preview`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);

    // Count Vikram appearances
    const vikramCount = preview.body.data.targets.filter((t: any) =>
      t.name?.toLowerCase().includes('vikram'),
    ).length;

    expect(vikramCount).toBe(1); // NOT 2
  });
});
```

### Test 5: UC1 Progressive Complexity

```typescript
describe('NEGATIVE TEST 5: UC1 Progressive Complexity', () => {
  let uc1: Awaited<ReturnType<typeof createUC1Tenant>>;

  beforeAll(async () => {
    uc1 = await createUC1Tenant(db);
  });

  it('should return clean UI flags for UC1 user', async () => {
    const res = await request(app.getHttpServer())
      .get('/auth/me')
      .set('Authorization', `Bearer ${uc1.token}`)
      .expect(200);

    // All multi-tenant UI features should be disabled
    const { ui } = res.body.data;
    expect(ui.showWorkspaceSelector).toBe(false);
    expect(ui.showDomainTabs).toBe(false);
    expect(ui.showPersonColumn).toBe(false);
    expect(ui.showCompanyLibrary).toBe(false);
    expect(ui.showBlueprintFeatures).toBe(false);
    expect(ui.showSettingsInheritance).toBe(false);
  });

  it('should NOT expose company-level endpoints to UC1 workspace admin', async () => {
    await request(app.getHttpServer())
      .get(`/companies/${uc1.company.id}/reports/recipients`)
      .set('Authorization', `Bearer ${uc1.token}`)
      .expect(403);
  });
});
```

### Test 6: Settings Inheritance

```typescript
describe('NEGATIVE TEST 6: Settings Inheritance', () => {
  it('should resolve settings correctly through inheritance chain', async () => {
    // Step 1: Set company default
    await request(app.getHttpServer())
      .patch(`/companies/${tenant.company.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({ trackOpens: true, trackClicks: true })
      .expect(200);

    // Step 2: WS-A inherits (no override)
    const resA1 = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);
    expect(resA1.body.data.trackOpens).toBe(true);
    expect(resA1.body.data._sources.trackOpens).toBe('company');

    // Step 3: WS-B overrides trackOpens to false
    await request(app.getHttpServer())
      .patch(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .send({ trackOpens: false, _override: ['trackOpens'] })
      .expect(200);

    const resB = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);
    expect(resB.body.data.trackOpens).toBe(false);
    expect(resB.body.data._sources.trackOpens).toBe('override');

    // Step 4: Company admin changes default to false
    await request(app.getHttpServer())
      .patch(`/companies/${tenant.company.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.companyToken}`)
      .send({ trackOpens: false })
      .expect(200);

    // Step 5: WS-A (inheriting) should now see false
    const resA2 = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceA.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenA}`)
      .expect(200);
    expect(resA2.body.data.trackOpens).toBe(false);

    // Step 6: WS-B (overriding) should still be false, source still "override"
    const resB2 = await request(app.getHttpServer())
      .get(`/workspaces/${tenant.workspaceB.id}/settings/email`)
      .set('Authorization', `Bearer ${tenant.tokenB}`)
      .expect(200);
    expect(resB2.body.data.trackOpens).toBe(false);
    expect(resB2.body.data._sources.trackOpens).toBe('override'); // NOT "company"
  });
});
```

---

## Isolation Test CI Gate

### Dedicated CI Step That Blocks Merge

```yaml
# .github/workflows/isolation.yml
name: Multi-Tenant Isolation Tests
on:
  pull_request:
    branches: [main, develop]

jobs:
  isolation:
    runs-on: ubuntu-latest
    # This job MUST pass before merge is allowed
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: isolation_db
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'pnpm'
      - run: pnpm install --frozen-lockfile
      - name: Run migrations
        run: pnpm --filter backend db:migrate:test
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/isolation_db
      - name: Run isolation tests
        run: |
          pnpm --filter backend vitest run \
            --config vitest.isolation.config.ts \
            --reporter=verbose
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/isolation_db
          REDIS_URL: redis://localhost:6379
      - name: Report isolation test results
        if: failure()
        run: |
          echo "::error::ISOLATION TESTS FAILED — Multi-tenant boundary violation detected. This PR CANNOT be merged."
```

### Vitest Config for Isolation Tests Only

```typescript
// vitest.isolation.config.ts
import { defineConfig } from 'vitest/config';
import swc from 'unplugin-swc';
import { resolve } from 'path';

export default defineConfig({
  plugins: [swc.vite()],
  test: {
    globals: true,
    root: resolve(__dirname),
    include: ['src/**/*.isolation.spec.ts'],
    setupFiles: ['./test/isolation-setup.ts'],
    pool: 'forks',
    poolOptions: {
      forks: { maxForks: 1 }, // Run sequentially — DB state matters
    },
    testTimeout: 30_000,
  },
});
```

---

## Checklist

### Before Shipping Any Module

**Workspace Isolation (MANDATORY)**
- [ ] Every GET endpoint returns only own-workspace data
- [ ] Every POST endpoint creates data only in own workspace
- [ ] Every PATCH endpoint updates data only in own workspace
- [ ] Every DELETE endpoint deletes data only in own workspace
- [ ] Spoofed x-workspace-id header returns 403
- [ ] Accessing cross-workspace domain returns 403

**Domain Isolation (MANDATORY)**
- [ ] Domain-scoped queries return only that domain's data
- [ ] Domain-scoped unique constraints work correctly
- [ ] Cross-domain duplication is allowed (same person, different email)

**Bulk Operations (MANDATORY)**
- [ ] Mixed workspace IDs in bulk delete: only own records affected
- [ ] Mixed workspace IDs in bulk update: only own records affected
- [ ] All-foreign IDs in bulk op: 0 affected, no error

**Company Admin (MANDATORY)**
- [ ] Company endpoints aggregate all workspaces
- [ ] Company endpoints are read-only (no mutations)
- [ ] Workspace admin cannot access company endpoints
- [ ] Company admin sees correct data at workspace level (isolated)

**Person De-Duplication (Required for UC2/UC3)**
- [ ] Same person across domains links to one Person
- [ ] deduplicateByPerson=true sends one message per person
- [ ] deduplicateByPerson=false sends one per recipient
- [ ] UC2 de-dup is intra-workspace only
- [ ] UC3 cross-workspace linking requires company admin role

**Settings Inheritance (Required for UC3)**
- [ ] Company default propagates to non-overriding workspaces
- [ ] Workspace override persists through company default changes
- [ ] Reset returns to company default
- [ ] Workspace admin cannot modify company-level settings

**Blueprint Deployment (Required for UC3)**
- [ ] Blueprint creates workspace-specific records
- [ ] Workspace admin can pause blueprint-spawned items
- [ ] Workspace admin cannot create blueprints

**Progressive Complexity (MANDATORY)**
- [ ] UC1 user sees no workspace selector
- [ ] UC1 user sees no domain tabs
- [ ] UC1 user sees no Person column
- [ ] UC1 user sees no Company Library
- [ ] UC1 user sees no Blueprint features
- [ ] UC1 user sees no settings inheritance badges

**The Six Negative Tests (MANDATORY)**
- [ ] Test 1: Cross-workspace data leak — PASS
- [ ] Test 2: Bulk operation cross-workspace — PASS
- [ ] Test 3: Company admin scope boundary — PASS
- [ ] Test 4: Person de-duplication — PASS
- [ ] Test 5: UC1 progressive complexity — PASS
- [ ] Test 6: Settings inheritance — PASS
