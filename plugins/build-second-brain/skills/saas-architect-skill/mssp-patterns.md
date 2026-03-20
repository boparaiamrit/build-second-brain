# MSSP Multi-Tenant Patterns (Enhancement to Core Skill)

These patterns extend the core tenant hierarchy (Company → Workspace → Domain → Data) with MSSP-specific capabilities discovered during deep codebase analysis.

## Three Customer Types

Every architecture decision must consider all three:

### UC1: Single Company, Single Domain
- 1 workspace, 1 domain, 1 admin
- Architecture is invisible — platform feels like simple single-tenant
- Person entity auto-created (1:1 with Recipient) but features hidden
- Company Library hidden (only 1 workspace)
- Settings inheritance hidden (nothing to inherit from)
- **Test:** Does the feature work without any multi-tenant UI? Zero extra clicks for UC1?

### UC2: Single Workspace, Multiple Domains
- 1 workspace, N domains (different identity providers)
- Same person exists across domains with different email addresses
- Person de-duplication is CRITICAL (within workspace)
- Domain tabs visible in admin UI
- Person column visible in data tables
- Bulk operations show domain breakdown + sync-protection warnings
- **Test:** When Vikram has jio.com and jiosaavn.com accounts, does the system treat him as ONE person?

### UC3: Multiple Workspaces (Full MSSP)
- N workspaces under 1 company, each with own domains
- CISO needs cross-workspace visibility
- Workspace isolation is SACRED — subsidiary A never sees subsidiary B data
- Company Library, Blueprint deployment, settings inheritance all required
- Person cross-workspace linking for people who exist in multiple subsidiaries
- **Test:** Can CISO create once and deploy everywhere? Can workspace admin manage independently?

## Person / Linked Identity Pattern

```
Company Level:
┌──────────┐
│  Person   │── primaryRecipientId (FK, unique)
│           │── companyId (FK)
│           │── matchConfidence (AUTO | CONFIRMED | MANUAL)
└──────────┘
      │ 1:N
      ▼
┌──────────┐
│PersonEmail│── personId (FK)
│           │── email (indexed for matching)
│           │── isPrimary
│           │── sourceRecipientId (FK)
└──────────┘

Workspace Level:
┌──────────┐
│Recipient  │── personId (FK, nullable)  ← links UP to Person
│           │── workspaceId
│           │── email
│           │── domainId
└──────────┘
```

**Rules:**
- Person is a POINTER, not a data store (no displayName, no secondaryEmails on Person itself)
- PersonEmail is a proper join table (replaces String[] arrays — enables indexed lookups)
- primaryRecipientId on Person resolves "which workspace sends campaign emails"
- Recipient.personId is nullable (UC1 users may never need Person linking)
- PersonMatchSuggestion has `scope` (INTRA_WORKSPACE for UC2, CROSS_WORKSPACE for UC3)

**Matching algorithm priority:**
1. UPN exact match (O365 ↔ O365) → AUTO confidence
2. Email prefix + displayName (O365 ↔ GSuite) → SUGGESTED
3. Name + department (any ↔ any) → SUGGESTED
4. Manual admin linking → MANUAL

## Company Library Pattern

Four-tier ownership for shared content (scenarios, training, templates, agents, tips):

```
GLOBAL     → isGlobal: true,  companyId: null,  workspaceId: null
COMPANY    → isGlobal: false, companyId: set,   workspaceId: null
WORKSPACE  → isGlobal: false, companyId: null,  workspaceId: set
CLONED     → clonedFromId: set, workspaceId: set
```

**Schema change (add to any shareable entity):**
```typescript
companyId    String?   // null = global or workspace-owned
company      Company?  @relation(fields: [companyId], references: [id])
@@index([companyId])
```

**Visibility filter:**
```typescript
// "All" tab: workspace + company + global
WHERE (workspaceId = X) OR (companyId = company.id) OR (isGlobal = true)

// "Company Library" tab
WHERE companyId = company.id AND workspaceId IS NULL

// "My Items" tab
WHERE workspaceId = X
```

**Apply to:** Scenarios, Training (Card + Conversation), Email Templates, Landing Templates, LiveKit Agents, Voice Configs, JIT Tips, JIT Trigger Rules

## Blueprint Pattern

Company Admin defines config once → system deploys to multiple workspaces → each workspace executes independently → company dashboard aggregates.

```
CampaignBlueprint (company level)
├── companyId
├── name, scenarios, training, schedule
├── targetWorkspaceIds[]
├── deduplicateByPerson: boolean
└── campaigns[]  ← spawned workspace campaigns (blueprintId FK)
```

**Apply to:** Campaigns, Announcements, Vishing

**Execution flow:**
1. Company Admin creates Blueprint
2. Selects target workspaces
3. `deploy-blueprint` BullMQ job: for each workspace → create Campaign/Announcement with `blueprintId` FK
4. Each workspace campaign uses own domain, sender, sending config
5. Company dashboard: `SELECT * FROM campaigns WHERE blueprintId = X` → aggregate stats

## Settings Inheritance Pattern

Company sets defaults → Workspaces inherit → Workspace can override specific fields.

```
CompanyDefault{Module}Settings
├── companyId (unique)
├── {inheritable fields only}
└── (no workspace-specific fields like phishingDomains, SSO credentials)

{Module}Settings (workspace level)
├── workspaceId (unique)
├── useCompanyDefaults: boolean
├── overriddenFields: string[]    ← tracks WHICH fields are overridden
├── {all fields — both inheritable and workspace-specific}
```

**Resolution algorithm:**
```typescript
function resolveField(workspace, company, fieldName) {
  if (isAlwaysWorkspaceSpecific(fieldName)) return workspace[fieldName]
  if (!workspace.useCompanyDefaults) {
    if (workspace.overriddenFields.includes(fieldName)) return workspace[fieldName]
  }
  if (company[fieldName] !== undefined) return company[fieldName]
  return systemDefault[fieldName]
}
```

**Always workspace-specific (NEVER inherit):**
- SSO credentials (per-tenant OAuth)
- Phishing domains
- Test employee emails
- Sender email addresses
- Portal branding (logo, colors, login page)
- SMTP/O365 configuration

**Inheritable from company:**
- Training policy (expiry, quiz criteria, re-attempts)
- Campaign policy (tracking, reporting, training assignment)
- Portal features (leaderboard, badges, points, widgets)
- Team portal visibility toggles
- Recipient settings (unique fields, profile completeness)

## Admin Role Pattern

Three patterns of administration:

**Pattern A: Dedicated admin per workspace**
- Each subsidiary has own IT security team
- CISO sees company dashboard only
- Workspace admins cannot see other workspaces

**Pattern B: Single admin manages all workspaces**
- One person with Company Admin role
- Uses workspace selector to switch context
- Creates Blueprints at company level

**Pattern C: Mixed (most common for MSSP)**
- Company level: CISO + 2 Company Admins (Blueprint, Library, Reports)
- Workspace level: 1-2 admins per subsidiary (day-to-day operations)
- Some subsidiaries fully self-managed, others rely on company team

**Permission matrix:**
| Action | Company Owner | Company Admin | Workspace Admin | Workspace Member |
|--------|:---:|:---:|:---:|:---:|
| Create workspace | YES | YES | NO | NO |
| View all workspaces | YES | YES | NO | NO |
| Create Company Library items | YES | YES | NO | NO |
| Create/deploy Blueprint | YES | YES | NO | NO |
| Set company default settings | YES | YES | NO | NO |
| Create workspace campaign/training | YES | YES | YES | NO |
| Override workspace settings | YES | YES | YES | NO |
| Manage workspace recipients | YES | YES | YES | READ |
| View company reports | YES | YES | NO | NO |
| View workspace reports | YES | YES | YES | NO |
| Link Persons cross-workspace | YES | YES | NO | NO |
| Link Persons intra-workspace | YES | YES | YES | NO |
| Pause Blueprint-spawned item in own WS | YES | YES | YES | NO |

## Cross-Workspace Training Credit

When Person completes training in one workspace, credit in others:

```
TrainingTargets (enhanced):
├── completionType: DIRECT | CROSS_WS_CREDIT
├── creditSourceRecipientId: String?    ← who actually completed
├── creditSourceWorkspaceId: String?    ← where completion happened
```

**Flow:**
1. Rajesh completes training in Workspace-A
2. Background job: find Person → find linked Recipients in other workspaces
3. For each linked Recipient: create TrainingTargets with `completionType: CROSS_WS_CREDIT`
4. Company report: "82.5% completed" (Person-level, not inflated recipient-level)

## De-Duplication Rules

| Context | UC1 | UC2 | UC3 |
|---------|-----|-----|-----|
| Campaign targeting | By recipientId (standard) | By Person within workspace | By Person across workspaces |
| Training enrollment | By recipientId | By Person (1 enrollment per Person) | By Person + cross-WS credit |
| Announcement targeting | By recipientId | By Person (1 email per Person) | By Person + Blueprint |
| Vishing targeting | By recipientId | By Person + phone number | By Person + phone across WS |
| Reporting headcount | Raw recipient count | Unique Person count | Unique Person count (cross-WS) |

## Progressive Complexity Rule

UC1 users must NEVER see UC3 complexity. Use progressive disclosure:

```
IF company.workspaceCount === 1:
  HIDE workspace selector
  HIDE "All Workspaces" view
  HIDE Company Library tabs
  HIDE Blueprint features
  HIDE settings inheritance badges

IF workspace.domainCount === 1:
  HIDE domain tabs
  HIDE Person column (show for UC2+)
  HIDE domain breakdown in bulk ops

IF workspace.domainCount > 1 OR company.workspaceCount > 1:
  SHOW Person column
  SHOW de-duplication metrics
  SHOW domain tabs
```

This ensures Zerodha (UC1) sees a simple, clean interface while Tata Group (UC3) sees the full MSSP capabilities.
