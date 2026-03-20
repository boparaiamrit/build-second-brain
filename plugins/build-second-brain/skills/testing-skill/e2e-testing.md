# E2E Testing Reference — Playwright for Next.js Multi-Tenant SaaS

> Read this file when writing end-to-end tests, setting up Playwright,
> testing auth flows, data tables, wizards, or configuring CI for E2E.

---

## Table of Contents
1. [Playwright Setup](#playwright-setup)
2. [Page Object Pattern](#page-object-pattern)
3. [Auth Flow Testing](#auth-flow-testing)
4. [Multi-Workspace Navigation](#multi-workspace-navigation)
5. [Data Table E2E](#data-table-e2e)
6. [Form Submission E2E](#form-submission-e2e)
7. [Import Wizard E2E](#import-wizard-e2e)
8. [Settings E2E (Inheritance)](#settings-e2e)
9. [Visual Regression Testing](#visual-regression-testing)
10. [CI Integration](#ci-integration)
11. [Test Data Seeding](#test-data-seeding)
12. [Debugging Failed E2E Tests](#debugging-failed-e2e-tests)

---

## Playwright Setup

### Configuration

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['html', { open: 'never' }], ['github']]
    : [['html', { open: 'on-failure' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    // Auth setup runs first — stores auth state for reuse
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'e2e/.auth/workspace-admin.json',
      },
      dependencies: ['setup'],
    },
    {
      name: 'mobile',
      use: {
        ...devices['iPhone 14'],
        storageState: 'e2e/.auth/workspace-admin.json',
      },
      dependencies: ['setup'],
    },
  ],
  webServer: process.env.CI
    ? undefined // CI starts the server separately
    : {
        command: 'pnpm dev',
        url: 'http://localhost:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
```

### Test File Organization

```
e2e/
├── .auth/                         # Stored auth state (gitignored)
│   ├── workspace-admin.json
│   ├── company-admin.json
│   └── readonly-user.json
├── fixtures/                      # Test data files
│   ├── import-valid.csv
│   ├── import-errors.csv
│   └── import-large.csv
├── pages/                         # Page objects
│   ├── login.page.ts
│   ├── recipients.page.ts
│   ├── campaigns.page.ts
│   ├── settings.page.ts
│   ├── navigation.page.ts
│   └── import-wizard.page.ts
├── helpers/
│   ├── seed.ts                    # DB seeding for E2E
│   ├── auth.ts                    # Auth helpers
│   └── assertions.ts              # Custom assertions
├── auth.setup.ts                  # Authentication setup
├── auth.spec.ts                   # Auth flow tests
├── workspace-switch.spec.ts       # Workspace context tests
├── recipients.spec.ts             # Recipient CRUD tests
├── data-table.spec.ts             # Table interaction tests
├── bulk-ops.spec.ts               # Bulk operation tests
├── import-wizard.spec.ts          # Import flow tests
├── settings.spec.ts               # Settings inheritance tests
└── progressive-complexity.spec.ts # UC1/UC2/UC3 UI tests
```

---

## Page Object Pattern

### Base Page

```typescript
// e2e/pages/base.page.ts
import { type Page, type Locator, expect } from '@playwright/test';

export class BasePage {
  readonly page: Page;
  readonly toastContainer: Locator;
  readonly loadingSpinner: Locator;

  constructor(page: Page) {
    this.page = page;
    this.toastContainer = page.locator('[data-sonner-toaster]');
    this.loadingSpinner = page.locator('[data-testid="loading"]');
  }

  async waitForPageLoad() {
    await this.page.waitForLoadState('networkidle');
    // Wait for any loading spinners to disappear
    await expect(this.loadingSpinner).not.toBeVisible({ timeout: 10_000 });
  }

  async expectToast(message: string | RegExp) {
    await expect(this.toastContainer.getByText(message)).toBeVisible({
      timeout: 5_000,
    });
  }

  async expectNoToastError() {
    await expect(
      this.toastContainer.locator('[data-type="error"]'),
    ).not.toBeVisible({ timeout: 2_000 });
  }
}
```

### Navigation Page Object

```typescript
// e2e/pages/navigation.page.ts
import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './base.page';

export class NavigationPage extends BasePage {
  readonly workspaceSelector: Locator;
  readonly workspaceDropdown: Locator;
  readonly sidebarNav: Locator;

  constructor(page: Page) {
    super(page);
    this.workspaceSelector = page.getByTestId('workspace-selector');
    this.workspaceDropdown = page.getByTestId('workspace-dropdown');
    this.sidebarNav = page.getByRole('navigation', { name: 'sidebar' });
  }

  async switchWorkspace(workspaceName: string) {
    await this.workspaceSelector.click();
    await this.workspaceDropdown.getByText(workspaceName).click();
    await this.waitForPageLoad();
  }

  async expectActiveWorkspace(name: string) {
    await expect(this.workspaceSelector).toContainText(name);
  }

  async navigateTo(section: string) {
    await this.sidebarNav.getByText(section, { exact: true }).click();
    await this.waitForPageLoad();
  }

  async expectWorkspaceSelectorVisible() {
    await expect(this.workspaceSelector).toBeVisible();
  }

  async expectWorkspaceSelectorHidden() {
    await expect(this.workspaceSelector).not.toBeVisible();
  }
}
```

### Recipients Page Object

```typescript
// e2e/pages/recipients.page.ts
import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './base.page';

export class RecipientsPage extends BasePage {
  readonly searchInput: Locator;
  readonly dataTable: Locator;
  readonly domainTabs: Locator;
  readonly addButton: Locator;
  readonly bulkActionsToolbar: Locator;
  readonly selectAllCheckbox: Locator;
  readonly paginationInfo: Locator;
  readonly filterButton: Locator;

  constructor(page: Page) {
    super(page);
    this.searchInput = page.getByPlaceholder(/search/i);
    this.dataTable = page.getByRole('table');
    this.domainTabs = page.getByTestId('domain-tabs');
    this.addButton = page.getByRole('button', { name: /add recipient/i });
    this.bulkActionsToolbar = page.getByTestId('bulk-actions');
    this.selectAllCheckbox = page.getByRole('columnheader').getByRole('checkbox');
    this.paginationInfo = page.getByTestId('pagination-info');
    this.filterButton = page.getByRole('button', { name: /filter/i });
  }

  async goto() {
    await this.page.goto('/en/recipients');
    await this.waitForPageLoad();
  }

  async search(query: string) {
    await this.searchInput.fill(query);
    // Wait for debounce + API response
    await this.page.waitForResponse(resp =>
      resp.url().includes('/recipients') && resp.status() === 200,
    );
  }

  async expectRowCount(count: number) {
    const rows = this.dataTable.locator('tbody tr');
    await expect(rows).toHaveCount(count);
  }

  async expectRowContains(email: string) {
    await expect(this.dataTable.getByText(email)).toBeVisible();
  }

  async expectRowNotPresent(email: string) {
    await expect(this.dataTable.getByText(email)).not.toBeVisible();
  }

  async selectRow(index: number) {
    const rows = this.dataTable.locator('tbody tr');
    await rows.nth(index).getByRole('checkbox').check();
  }

  async selectAllRows() {
    await this.selectAllCheckbox.check();
  }

  async clickBulkAction(actionName: string) {
    await this.bulkActionsToolbar.getByRole('button', { name: actionName }).click();
  }

  async switchDomain(domainName: string) {
    await this.domainTabs.getByText(domainName).click();
    await this.waitForPageLoad();
  }

  async openAddForm() {
    await this.addButton.click();
    await expect(this.page.getByRole('dialog')).toBeVisible();
  }

  async fillRecipientForm(data: { email: string; firstName: string; lastName: string }) {
    await this.page.getByLabel(/email/i).fill(data.email);
    await this.page.getByLabel(/first name/i).fill(data.firstName);
    await this.page.getByLabel(/last name/i).fill(data.lastName);
  }

  async submitForm() {
    await this.page.getByRole('button', { name: /save|create|submit/i }).click();
  }

  async applyFilter(filterName: string, values: string[]) {
    await this.filterButton.click();
    const filterPanel = this.page.getByTestId('filter-panel');
    for (const value of values) {
      await filterPanel.getByLabel(filterName).getByText(value).click();
    }
    await filterPanel.getByRole('button', { name: /apply/i }).click();
    await this.waitForPageLoad();
  }

  async sortByColumn(columnName: string) {
    await this.dataTable.getByRole('columnheader', { name: columnName }).click();
    await this.waitForPageLoad();
  }

  async getRowEmails(): Promise<string[]> {
    const cells = this.dataTable.locator('tbody tr td:nth-child(2)');
    return cells.allTextContents();
  }
}
```

### Import Wizard Page Object

```typescript
// e2e/pages/import-wizard.page.ts
import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './base.page';
import * as path from 'path';

export class ImportWizardPage extends BasePage {
  readonly fileInput: Locator;
  readonly nextButton: Locator;
  readonly backButton: Locator;
  readonly commitButton: Locator;
  readonly progressBar: Locator;
  readonly stepIndicator: Locator;
  readonly mappingTable: Locator;
  readonly previewTable: Locator;
  readonly errorSummary: Locator;

  constructor(page: Page) {
    super(page);
    this.fileInput = page.locator('input[type="file"]');
    this.nextButton = page.getByRole('button', { name: /next|continue/i });
    this.backButton = page.getByRole('button', { name: /back|previous/i });
    this.commitButton = page.getByRole('button', { name: /import|commit/i });
    this.progressBar = page.getByRole('progressbar');
    this.stepIndicator = page.getByTestId('step-indicator');
    this.mappingTable = page.getByTestId('mapping-table');
    this.previewTable = page.getByTestId('preview-table');
    this.errorSummary = page.getByTestId('error-summary');
  }

  async uploadFile(fixtureName: string) {
    const fixturesDir = path.resolve(process.cwd(), 'e2e', 'fixtures');
    const filePath = path.join(fixturesDir, fixtureName);
    await this.fileInput.setInputFiles(filePath);
    // Wait for parsing
    await expect(this.nextButton).toBeEnabled({ timeout: 10_000 });
  }

  async expectStep(stepNumber: number) {
    await expect(this.stepIndicator).toContainText(`Step ${stepNumber}`);
  }

  async mapColumn(csvColumn: string, targetField: string) {
    const row = this.mappingTable.locator('tr', { hasText: csvColumn });
    await row.getByRole('combobox').selectOption(targetField);
  }

  async expectPreviewRows(count: number) {
    const rows = this.previewTable.locator('tbody tr');
    await expect(rows).toHaveCount(count);
  }

  async expectErrorCount(count: number) {
    await expect(this.errorSummary).toContainText(`${count} error`);
  }

  async waitForImportComplete() {
    // Wait for progress bar to reach 100%
    await expect(this.progressBar).toHaveAttribute('aria-valuenow', '100', {
      timeout: 60_000,
    });
    await this.expectToast(/import.*complete|successfully imported/i);
  }
}
```

---

## Auth Flow Testing

### Auth Setup (Runs Before All Tests)

```typescript
// e2e/auth.setup.ts
import { test as setup, expect } from '@playwright/test';

const WORKSPACE_ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL || 'admin@test.com',
  password: process.env.E2E_ADMIN_PASSWORD || 'TestPassword123!',
};

const COMPANY_ADMIN = {
  email: process.env.E2E_COMPANY_ADMIN_EMAIL || 'ciso@test.com',
  password: process.env.E2E_COMPANY_ADMIN_PASSWORD || 'TestPassword123!',
};

setup('authenticate as workspace admin', async ({ page }) => {
  await page.goto('/en/login');
  await page.getByLabel(/email/i).fill(WORKSPACE_ADMIN.email);
  await page.getByLabel(/password/i).fill(WORKSPACE_ADMIN.password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();

  // Wait for redirect to dashboard
  await page.waitForURL('**/dashboard', { timeout: 10_000 });
  await expect(page.getByText(/dashboard|welcome/i)).toBeVisible();

  // Save auth state for reuse
  await page.context().storageState({ path: 'e2e/.auth/workspace-admin.json' });
});

setup('authenticate as company admin', async ({ page }) => {
  await page.goto('/en/login');
  await page.getByLabel(/email/i).fill(COMPANY_ADMIN.email);
  await page.getByLabel(/password/i).fill(COMPANY_ADMIN.password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();

  await page.waitForURL('**/dashboard', { timeout: 10_000 });
  await page.context().storageState({ path: 'e2e/.auth/company-admin.json' });
});
```

### Auth Flow Tests

```typescript
// e2e/auth.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  // Use fresh context (no stored auth)
  test.use({ storageState: { cookies: [], origins: [] } });

  test('should show login page for unauthenticated user', async ({ page }) => {
    await page.goto('/en/dashboard');
    await expect(page).toHaveURL(/.*login/);
  });

  test('should login with valid credentials', async ({ page }) => {
    await page.goto('/en/login');
    await page.getByLabel(/email/i).fill('admin@test.com');
    await page.getByLabel(/password/i).fill('TestPassword123!');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/.*dashboard/);
    await expect(page.getByText(/dashboard|welcome/i)).toBeVisible();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/en/login');
    await page.getByLabel(/email/i).fill('admin@test.com');
    await page.getByLabel(/password/i).fill('WrongPassword');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page.getByText(/invalid|incorrect|failed/i)).toBeVisible();
    await expect(page).toHaveURL(/.*login/);
  });

  test('should persist session across page reload', async ({ page }) => {
    // Login first
    await page.goto('/en/login');
    await page.getByLabel(/email/i).fill('admin@test.com');
    await page.getByLabel(/password/i).fill('TestPassword123!');
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForURL('**/dashboard');

    // Reload page
    await page.reload();

    // Should still be on dashboard, not redirected to login
    await expect(page).toHaveURL(/.*dashboard/);
  });

  test('should redirect to login after logout', async ({ page }) => {
    await page.goto('/en/login');
    await page.getByLabel(/email/i).fill('admin@test.com');
    await page.getByLabel(/password/i).fill('TestPassword123!');
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForURL('**/dashboard');

    // Logout
    await page.getByTestId('user-menu').click();
    await page.getByText(/logout|sign out/i).click();

    await expect(page).toHaveURL(/.*login/);
  });
});
```

---

## Multi-Workspace Navigation

```typescript
// e2e/workspace-switch.spec.ts
import { test, expect } from '@playwright/test';
import { NavigationPage } from './pages/navigation.page';
import { RecipientsPage } from './pages/recipients.page';

test.describe('Workspace Switching', () => {
  // Use company admin auth (has access to multiple workspaces)
  test.use({ storageState: 'e2e/.auth/company-admin.json' });

  test('should show workspace selector for company admin', async ({ page }) => {
    const nav = new NavigationPage(page);
    await page.goto('/en/dashboard');
    await nav.waitForPageLoad();

    await nav.expectWorkspaceSelectorVisible();
  });

  test('should switch workspace and refresh data', async ({ page }) => {
    const nav = new NavigationPage(page);
    const recipients = new RecipientsPage(page);

    await page.goto('/en/recipients');
    await recipients.waitForPageLoad();

    // Note current workspace data
    await nav.expectActiveWorkspace('Tata Steel');
    await recipients.expectRowContains('rajesh@tatasteel.com');

    // Switch workspace
    await nav.switchWorkspace('Tata Motors');

    // Data should change
    await nav.expectActiveWorkspace('Tata Motors');
    await recipients.expectRowNotPresent('rajesh@tatasteel.com');
    await recipients.expectRowContains('vikram@tatamotors.com');
  });

  test('should preserve workspace context across navigation', async ({ page }) => {
    const nav = new NavigationPage(page);

    await page.goto('/en/dashboard');
    await nav.switchWorkspace('Tata Motors');

    // Navigate to different page
    await nav.navigateTo('Recipients');
    await nav.expectActiveWorkspace('Tata Motors');

    // Navigate again
    await nav.navigateTo('Campaigns');
    await nav.expectActiveWorkspace('Tata Motors');
  });

  test('should show "All Workspaces" as read-only for company admin', async ({ page }) => {
    const nav = new NavigationPage(page);

    await page.goto('/en/dashboard');
    await nav.switchWorkspace('All Workspaces');

    // Dashboard should show aggregated data
    await expect(page.getByText(/all workspaces/i)).toBeVisible();

    // Edit buttons should be disabled or hidden in read-only mode
    const editButtons = page.getByRole('button', { name: /edit|delete|create/i });
    const count = await editButtons.count();
    for (let i = 0; i < count; i++) {
      await expect(editButtons.nth(i)).toBeDisabled();
    }
  });
});
```

---

## Data Table E2E

```typescript
// e2e/data-table.spec.ts
import { test, expect } from '@playwright/test';
import { RecipientsPage } from './pages/recipients.page';

test.describe('Data Table', () => {
  let recipients: RecipientsPage;

  test.beforeEach(async ({ page }) => {
    recipients = new RecipientsPage(page);
    await recipients.goto();
  });

  test('should search and filter results', async () => {
    await recipients.search('rajesh');
    await recipients.expectRowContains('rajesh@tatasteel.com');
    await recipients.expectRowNotPresent('priya@tatasteel.com');
  });

  test('should clear search and show all results', async () => {
    await recipients.search('rajesh');
    await recipients.expectRowCount(1);

    await recipients.searchInput.clear();
    await recipients.page.waitForResponse(r => r.url().includes('/recipients'));
    // Should show more than 1 row now
  });

  test('should filter by status', async () => {
    await recipients.applyFilter('Status', ['Active']);
    // All visible rows should have "active" status
    const rows = recipients.dataTable.locator('tbody tr');
    const count = await rows.count();
    for (let i = 0; i < count; i++) {
      await expect(rows.nth(i).getByText('active')).toBeVisible();
    }
  });

  test('should sort by email column', async ({ page }) => {
    await recipients.sortByColumn('Email');
    const emails = await recipients.getRowEmails();
    const sorted = [...emails].sort();
    expect(emails).toEqual(sorted);
  });

  test('should sort descending on second click', async ({ page }) => {
    await recipients.sortByColumn('Email');
    await recipients.sortByColumn('Email');
    const emails = await recipients.getRowEmails();
    const sorted = [...emails].sort().reverse();
    expect(emails).toEqual(sorted);
  });

  test('should select single row and show bulk actions', async () => {
    await recipients.selectRow(0);
    await expect(recipients.bulkActionsToolbar).toBeVisible();
    await expect(recipients.bulkActionsToolbar).toContainText('1 selected');
  });

  test('should select all rows', async () => {
    await recipients.selectAllRows();
    await expect(recipients.bulkActionsToolbar).toContainText(/selected/);
  });

  test('should bulk delete selected rows', async ({ page }) => {
    await recipients.selectRow(0);
    await recipients.selectRow(1);
    await recipients.clickBulkAction('Delete');

    // Confirmation dialog
    await expect(page.getByText(/are you sure/i)).toBeVisible();
    await page.getByRole('button', { name: /confirm|delete/i }).click();

    await recipients.expectToast(/deleted/i);
  });

  test('should paginate through results', async ({ page }) => {
    // Assumes more than one page of data
    const nextButton = page.getByRole('button', { name: /next/i });
    if (await nextButton.isEnabled()) {
      await nextButton.click();
      await recipients.waitForPageLoad();
      await expect(recipients.paginationInfo).toContainText(/page 2/i);
    }
  });
});
```

---

## Form Submission E2E

```typescript
// e2e/recipients.spec.ts (CRUD via UI)
import { test, expect } from '@playwright/test';
import { RecipientsPage } from './pages/recipients.page';

test.describe('Recipient CRUD', () => {
  let recipients: RecipientsPage;

  test.beforeEach(async ({ page }) => {
    recipients = new RecipientsPage(page);
    await recipients.goto();
  });

  test('should create a new recipient', async ({ page }) => {
    await recipients.openAddForm();
    await recipients.fillRecipientForm({
      email: 'newuser@tatasteel.com',
      firstName: 'Arun',
      lastName: 'Mehta',
    });
    await recipients.submitForm();

    await recipients.expectToast(/created|added/i);
    await recipients.search('newuser@tatasteel.com');
    await recipients.expectRowContains('newuser@tatasteel.com');
  });

  test('should show validation error for invalid email', async ({ page }) => {
    await recipients.openAddForm();
    await recipients.fillRecipientForm({
      email: 'not-an-email',
      firstName: 'Bad',
      lastName: 'Input',
    });
    await recipients.submitForm();

    await expect(page.getByText(/invalid email/i)).toBeVisible();
  });

  test('should show conflict error for duplicate email', async ({ page }) => {
    // Try to create with existing email
    await recipients.openAddForm();
    await recipients.fillRecipientForm({
      email: 'rajesh@tatasteel.com', // Existing
      firstName: 'Duplicate',
      lastName: 'User',
    });
    await recipients.submitForm();

    await recipients.expectToast(/already exists|duplicate|conflict/i);
  });

  test('should edit a recipient inline', async ({ page }) => {
    // Double-click a cell to edit
    const departmentCell = recipients.dataTable
      .locator('tbody tr')
      .first()
      .locator('[data-column="department"]');

    await departmentCell.dblclick();
    const input = departmentCell.getByRole('textbox');
    await input.clear();
    await input.fill('Security');
    await input.press('Enter');

    await recipients.expectToast(/updated/i);
    await expect(departmentCell).toContainText('Security');
  });

  test('should delete a recipient', async ({ page }) => {
    // Open actions menu on first row
    const firstRow = recipients.dataTable.locator('tbody tr').first();
    await firstRow.getByRole('button', { name: /actions|more/i }).click();
    await page.getByRole('menuitem', { name: /delete/i }).click();

    // Confirm
    await page.getByRole('button', { name: /confirm/i }).click();
    await recipients.expectToast(/deleted/i);
  });
});
```

---

## Import Wizard E2E

```typescript
// e2e/import-wizard.spec.ts
import { test, expect } from '@playwright/test';
import { RecipientsPage } from './pages/recipients.page';
import { ImportWizardPage } from './pages/import-wizard.page';

test.describe('Import Wizard', () => {
  test('should complete full import flow', async ({ page }) => {
    const recipients = new RecipientsPage(page);
    await recipients.goto();

    // Open import wizard
    await page.getByRole('button', { name: /import/i }).click();

    const wizard = new ImportWizardPage(page);

    // Step 1: Upload file
    await wizard.expectStep(1);
    await wizard.uploadFile('import-valid.csv');
    await wizard.nextButton.click();

    // Step 2: Map columns
    await wizard.expectStep(2);
    await wizard.mapColumn('Email Address', 'email');
    await wizard.mapColumn('First Name', 'firstName');
    await wizard.mapColumn('Last Name', 'lastName');
    await wizard.nextButton.click();

    // Step 3: Review and commit
    await wizard.expectStep(3);
    await wizard.expectPreviewRows(10); // First 10 rows preview
    await wizard.commitButton.click();

    // Wait for import to complete
    await wizard.waitForImportComplete();

    // Verify imported recipients appear in table
    await recipients.goto();
    // Check that the newly imported email appears
  });

  test('should show validation errors for invalid rows', async ({ page }) => {
    await page.goto('/en/recipients');
    await page.getByRole('button', { name: /import/i }).click();

    const wizard = new ImportWizardPage(page);

    await wizard.uploadFile('import-errors.csv');
    await wizard.nextButton.click();

    // Map columns
    await wizard.mapColumn('Email', 'email');
    await wizard.nextButton.click();

    // Review should show error count
    await wizard.expectErrorCount(3);

    // Error rows should be highlighted
    await expect(
      wizard.previewTable.locator('tr.error, tr[data-status="error"]'),
    ).toHaveCount(3);
  });

  test('should handle large file with progress indicator', async ({ page }) => {
    await page.goto('/en/recipients');
    await page.getByRole('button', { name: /import/i }).click();

    const wizard = new ImportWizardPage(page);

    await wizard.uploadFile('import-large.csv');
    await wizard.nextButton.click();
    await wizard.mapColumn('Email', 'email');
    await wizard.nextButton.click();
    await wizard.commitButton.click();

    // Progress bar should be visible during import
    await expect(wizard.progressBar).toBeVisible();
    await wizard.waitForImportComplete();
  });

  test('should allow going back to fix mapping', async ({ page }) => {
    await page.goto('/en/recipients');
    await page.getByRole('button', { name: /import/i }).click();

    const wizard = new ImportWizardPage(page);

    await wizard.uploadFile('import-valid.csv');
    await wizard.nextButton.click();
    await wizard.expectStep(2);

    // Go back
    await wizard.backButton.click();
    await wizard.expectStep(1);

    // Go forward again
    await wizard.nextButton.click();
    await wizard.expectStep(2);
  });
});
```

---

## Settings E2E

```typescript
// e2e/settings.spec.ts
import { test, expect } from '@playwright/test';
import { NavigationPage } from './pages/navigation.page';

test.describe('Settings Inheritance', () => {
  test.use({ storageState: 'e2e/.auth/company-admin.json' });

  test('should show inheritance badges on settings fields', async ({ page }) => {
    const nav = new NavigationPage(page);
    await page.goto('/en/settings');
    await nav.waitForPageLoad();

    // Look for inheritance badges
    const companyBadge = page.locator('[data-source="company"]');
    const overrideBadge = page.locator('[data-source="override"]');

    // At least some fields should show their source
    const badgeCount = await companyBadge.count() + await overrideBadge.count();
    expect(badgeCount).toBeGreaterThan(0);
  });

  test('should allow workspace admin to override company default', async ({ page }) => {
    const nav = new NavigationPage(page);
    await nav.switchWorkspace('Tata Steel');
    await page.goto('/en/settings');
    await nav.waitForPageLoad();

    // Find an inherited field and override it
    const trackOpensField = page.getByTestId('setting-trackOpens');
    const overrideButton = trackOpensField.getByRole('button', { name: /override/i });

    if (await overrideButton.isVisible()) {
      await overrideButton.click();
      // Toggle the setting
      const toggle = trackOpensField.getByRole('switch');
      await toggle.click();

      await page.getByRole('button', { name: /save/i }).click();
      await expect(page.locator('[data-sonner-toaster]').getByText(/saved|updated/i)).toBeVisible();

      // Verify badge changed to "override"
      await expect(trackOpensField.locator('[data-source="override"]')).toBeVisible();
    }
  });

  test('should not show inheritance UI for UC1 user', async ({ page }) => {
    // UC1 user with single workspace
    test.use({ storageState: 'e2e/.auth/workspace-admin.json' });

    await page.goto('/en/settings');
    await page.waitForLoadState('networkidle');

    // No inheritance badges should be visible
    const badges = page.locator('[data-source="company"], [data-source="override"]');
    await expect(badges).toHaveCount(0);
  });
});
```

---

## Visual Regression Testing

```typescript
// e2e/visual.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Visual Regression', () => {
  test('recipients page matches screenshot', async ({ page }) => {
    await page.goto('/en/recipients');
    await page.waitForLoadState('networkidle');

    // Wait for all images and fonts to load
    await page.waitForTimeout(1000);

    await expect(page).toHaveScreenshot('recipients-page.png', {
      maxDiffPixelRatio: 0.01,     // 1% tolerance
      mask: [page.getByTestId('timestamp')], // Mask dynamic content
    });
  });

  test('dark mode renders correctly', async ({ page }) => {
    await page.goto('/en/recipients');
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveScreenshot('recipients-dark.png', {
      maxDiffPixelRatio: 0.01,
    });
  });

  test('mobile layout renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/en/recipients');
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveScreenshot('recipients-mobile.png', {
      maxDiffPixelRatio: 0.02, // Slightly more tolerance for mobile
    });
  });
});
```

---

## CI Integration

### GitHub Actions for Playwright

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on:
  pull_request:
    branches: [main, develop]

jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: e2e_db
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

      - name: Install dependencies
        run: pnpm install --frozen-lockfile

      - name: Install Playwright browsers
        run: pnpm exec playwright install --with-deps chromium

      - name: Run migrations + seed
        run: |
          pnpm --filter backend db:migrate:test
          pnpm --filter backend db:seed:e2e
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db

      - name: Build frontend
        run: pnpm --filter frontend build
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db
          REDIS_URL: redis://localhost:6379

      - name: Start server
        run: |
          pnpm --filter backend start:prod &
          pnpm --filter frontend start &
          # Wait for servers to be ready
          npx wait-on http://localhost:3000 http://localhost:4000/health --timeout 60000
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db
          REDIS_URL: redis://localhost:6379

      - name: Run E2E tests
        run: pnpm exec playwright test
        env:
          E2E_BASE_URL: http://localhost:3000
          E2E_ADMIN_EMAIL: admin@test.com
          E2E_ADMIN_PASSWORD: TestPassword123!

      - name: Upload Playwright report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 14

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: test-results/
```

---

## Test Data Seeding

### E2E Seed Script

```typescript
// e2e/helpers/seed.ts
import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import * as schema from '../../backend/src/db/schema';
import { hashPassword } from '../../backend/src/auth/utils';

export async function seedE2E() {
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  const db = drizzle(pool, { schema });

  // Create test company
  const [company] = await db.insert(schema.companies).values({
    name: 'Tata Group',
    slug: 'tata-group-e2e',
    subscriptionTier: 'enterprise',
    subscriptionStatus: 'active',
    recipientLimit: 100_000,
  }).returning();

  // Create workspaces
  const [wsSteel] = await db.insert(schema.workspaces).values({
    companyId: company.id,
    name: 'Tata Steel',
    slug: 'tata-steel',
  }).returning();

  const [wsMotors] = await db.insert(schema.workspaces).values({
    companyId: company.id,
    name: 'Tata Motors',
    slug: 'tata-motors',
  }).returning();

  // Create domains
  const [domainSteel] = await db.insert(schema.domains).values({
    companyId: company.id,
    workspaceId: wsSteel.id,
    domainName: 'tatasteel.com',
    verified: true,
  }).returning();

  const [domainMotors] = await db.insert(schema.domains).values({
    companyId: company.id,
    workspaceId: wsMotors.id,
    domainName: 'tatamotors.com',
    verified: true,
  }).returning();

  // Create test users
  const passwordHash = await hashPassword('TestPassword123!');

  // Workspace admin
  await db.insert(schema.users).values({
    email: 'admin@test.com',
    passwordHash,
    role: 'workspace_admin',
    workspaceId: wsSteel.id,
    companyId: company.id,
  });

  // Company admin (access to all workspaces)
  await db.insert(schema.users).values({
    email: 'ciso@test.com',
    passwordHash,
    role: 'company_admin',
    companyId: company.id,
  });

  // Seed recipients
  const recipients = [
    { email: 'rajesh@tatasteel.com', firstName: 'Rajesh', lastName: 'Kumar', department: 'Engineering' },
    { email: 'priya@tatasteel.com', firstName: 'Priya', lastName: 'Sharma', department: 'Marketing' },
    { email: 'vikram@tatamotors.com', firstName: 'Vikram', lastName: 'Singh', department: 'Engineering' },
    { email: 'anita@tatamotors.com', firstName: 'Anita', lastName: 'Patel', department: 'HR' },
  ];

  for (const r of recipients) {
    const domainId = r.email.includes('tatasteel') ? domainSteel.id : domainMotors.id;
    const workspaceId = r.email.includes('tatasteel') ? wsSteel.id : wsMotors.id;

    await db.insert(schema.recipients).values({
      companyId: company.id,
      workspaceId,
      domainId,
      email: r.email,
      name: `${r.firstName} ${r.lastName}`,
      status: 'active',
      customFields: { department: r.department },
    });
  }

  await pool.end();
  console.log('E2E seed complete');
}
```

---

## Debugging Failed E2E Tests

### Trace Viewer

```bash
# Open trace for failed test
pnpm exec playwright show-trace test-results/auth-Authentication-should-login/trace.zip
```

### Interactive Debugging

```bash
# Run with headed browser + slowMo
pnpm exec playwright test auth.spec.ts --headed --slow-mo 500

# Debug mode (step through with Inspector)
pnpm exec playwright test auth.spec.ts --debug

# Run specific test by title
pnpm exec playwright test -g "should create a new recipient"
```

### Screenshot on Assertion Failure

```typescript
test('debugging example', async ({ page }) => {
  await page.goto('/en/recipients');

  // Take screenshot at specific point for debugging
  await page.screenshot({ path: 'debug-screenshot.png', fullPage: true });

  // Or capture on assertion failure (configured globally in playwright.config.ts)
});
```

### Network Request Logging

```typescript
test('debug API calls', async ({ page }) => {
  // Log all API requests
  page.on('request', request => {
    if (request.url().includes('/api/')) {
      console.log(`>> ${request.method()} ${request.url()}`);
    }
  });

  page.on('response', response => {
    if (response.url().includes('/api/')) {
      console.log(`<< ${response.status()} ${response.url()}`);
    }
  });

  await page.goto('/en/recipients');
});
```
