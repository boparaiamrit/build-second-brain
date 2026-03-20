---
name: mssp-audit-skill
description: Exhaustive 5-phase audit of any module against UC1/UC2/UC3 multi-tenant requirements — covering data model, API, frontend, integration, and deployment. 48 checks across backend and frontend. Generates gap reports with severity scoring. Also enforces 10 mandatory planning questions before any new feature. Trigger when auditing a module for MSSP readiness, planning a new feature, reviewing architecture for multi-tenant compliance, or generating gap analysis reports.
---

# MSSP Multi-Tenant Audit Skill

## Purpose

Exhaustive 5-phase audit of ANY module against UC1/UC2/UC3 requirements — covering backend, frontend, data model, API, and UX. Nothing can be missed. Run this before shipping any module to MSSP customers.

## When to Use

- Before deploying a module to MSSP (UC3) customers
- Before claiming a module is "multi-tenant ready"
- When planning migration work from single-tenant to multi-tenant
- As a quality gate in feature development (run after building, before PR)
- When a stakeholder asks "is this ready for Tata Group / Reliance?"

## Five Audit Phases

```
Phase 1: DATA MODEL AUDIT (backend schema)
Phase 2: API & SERVICE AUDIT (backend logic)
Phase 3: FRONTEND AUDIT (components, state, UX)
Phase 4: INTEGRATION AUDIT (cross-module, campaign↔training, etc.)
Phase 5: DEPLOYMENT AUDIT (settings, migration, progressive complexity)
```

**Every phase produces a section in the final report. No phase can be skipped.**

---

## Phase 1: Data Model Audit

Inspect every Prisma model / Drizzle table for the module.

### Checks:

| # | Check | What to Look For | Pass Criteria |
|---|-------|-----------------|---------------|
| 1.1 | **workspaceId on every table** | Does every data table have `workspaceId` as a required FK? | Every table that stores user/content data has `workspaceId` NOT NULL |
| 1.2 | **Workspace-scoped unique constraints** | Are unique constraints scoped per workspace? e.g., `@@unique([workspaceId, email, deletedAt])` | No global unique constraints that would conflict across workspaces |
| 1.3 | **personId FK (nullable)** | Does the recipient/target table have `personId` for Person linking? | `personId String?` exists on Recipient and enrollment tables |
| 1.4 | **companyId for shareable content** | Do shareable entities (scenarios, training, templates) have `companyId`? | `companyId String?` exists on content tables meant for Company Library |
| 1.5 | **blueprintId FK** | Do campaign/announcement tables have `blueprintId` for Blueprint pattern? | `blueprintId String?` exists on Campaign, Announcement, VishingCampaign |
| 1.6 | **Settings inheritance fields** | Do settings tables have `useCompanyDefaults` + `overriddenFields[]`? | Both fields exist on every module's settings table |
| 1.7 | **Cross-workspace credit fields** | Does TrainingTargets have `completionType` + `creditSourceRecipientId`? | DIRECT and CROSS_WS_CREDIT enum values exist |
| 1.8 | **Soft delete support** | Do all tables have `deletedAt DateTime?`? | No hard deletes that would break Person linking |
| 1.9 | **Indexes on workspaceId** | Is there an index on `workspaceId` for every table? | `@@index([workspaceId])` exists |
| 1.10 | **Cascade rules** | Do FKs cascade correctly? (workspace delete → data delete, Person delete → unlink only) | `onDelete: Cascade` for workspace FK, `onDelete: SetNull` for personId |

### How to Check:
```bash
# Read all Prisma schema files for the module
grep -n "workspaceId\|companyId\|personId\|blueprintId\|useCompanyDefaults\|overriddenFields\|completionType\|deletedAt" prisma/schema/{module}.prisma
```

---

## Phase 2: API & Service Audit

Inspect every controller, service, and guard.

### Checks:

| # | Check | What to Look For | Pass Criteria |
|---|-------|-----------------|---------------|
| 2.1 | **x-workspace-id header required** | Does every non-public endpoint require workspace context? | JWT strategy extracts workspaceId from header or token |
| 2.2 | **WHERE workspaceId in every query** | Does every DB query include workspace scoping? | No query fetches data without `WHERE workspaceId = X` (except admin routes) |
| 2.3 | **Bulk ops enforce workspace boundary** | Can bulk delete/update touch records in other workspaces? | All bulk operations include `AND workspaceId = X` in WHERE clause |
| 2.4 | **Company-level endpoints exist** | Are there `/companies/:companyId/` endpoints for aggregation? | Company dashboard, Blueprint CRUD, Company Library CRUD endpoints exist |
| 2.5 | **CASL abilities check workspace** | Do permission checks verify workspace ownership? | `UserAbilityGuard` validates user has role in the specific workspace |
| 2.6 | **Person de-duplication in targeting** | Do campaign/training assignment services group by Person? | `deduplicateByPerson` flag exists and is checked before creating targets |
| 2.7 | **Idempotent enrollment** | Does training assignment check if already completed? | `skipIfCompleted` check before creating TrainingTargets |
| 2.8 | **Settings resolution service** | Is there a method that merges company defaults + workspace overrides? | `resolveSettings()` method exists that applies inheritance logic |
| 2.9 | **Blueprint deployment service** | Can a Blueprint be deployed to multiple workspaces? | `deployBlueprint()` creates workspace-specific records with `blueprintId` FK |
| 2.10 | **Cross-workspace query protection** | Can a workspace admin API ever return cross-workspace data? | No workspace-scoped endpoint joins or returns data from other workspaces |

### How to Check:
```bash
# Search for queries missing workspace scope
grep -rn "findMany\|findFirst\|updateMany\|deleteMany" src/{module}/ | grep -v "workspaceId"

# Search for unprotected endpoints
grep -rn "@Public\|@SkipAuth" src/{module}/
```

---

## Phase 3: Frontend Audit

Inspect pages, components, state management, and UX patterns.

### Checks:

| # | Check | What to Look For | Pass Criteria |
|---|-------|-----------------|---------------|
| 3.1 | **Workspace selector in nav** | Does the top nav have a workspace dropdown? | WorkspaceSelector component exists, sends `x-workspace-id` header |
| 3.2 | **Domain tabs in list views** | Are domain tabs shown (not cosmetic filter)? | DomainTabs component fetches real Domain records, passes `domainId` to API |
| 3.3 | **Person column in data tables** | Does the table show "N identities" for multi-domain persons? | Person column exists, shows link count, clickable to sidepanel |
| 3.4 | **Bulk ops domain breakdown** | When selecting across domains, does toolbar show "5 from domain-A, 3 from domain-B"? | Domain breakdown shown in bulk actions toolbar |
| 3.5 | **Sync-protected field warnings** | When editing a synced recipient's department, does UI warn "may revert on next sync"? | Warning shown for fields owned by identity provider |
| 3.6 | **Import asks for target domain** | Does CSV import wizard ask which domain to assign? | Domain selection step exists in import wizard |
| 3.7 | **Server-side pagination** | Does the list view use `?page=1&limit=50` instead of `?limit=10000`? | No `limit=10000` or fetch-all patterns |
| 3.8 | **Settings show inheritance badges** | Do settings fields show COMPANY/WORKSPACE/OVERRIDE badges? | Inheritance indicator component exists per settings field |
| 3.9 | **"All Workspaces" view is read-only** | Can Company Admin see aggregated data without editing? | "All Workspaces" option exists in workspace selector, shows read-only dashboard |
| 3.10 | **Progressive complexity** | Are UC3 features hidden for UC1 users? | Workspace selector hidden when 1 workspace, domain tabs hidden when 1 domain |
| 3.11 | **React Query for data fetching** | Is data fetched via `useQuery`/`useMutation` (not raw fetch)? | No `useEffect` + `fetch` + `useState` patterns |
| 3.12 | **Zustand for global state** | Is workspace context in Zustand (not scattered useState)? | WorkspaceStore exists with activeWorkspaceId |

### How to Check:
```bash
# Find fetch-all patterns
grep -rn "limit=10000\|limit: 10000" src/ app/ components/

# Find raw fetch in useEffect
grep -rn "useEffect.*fetch\|fetch.*then.*setData" src/ app/ components/

# Find missing workspace header
grep -rn "fetchApi\|fetch(" src/ | grep -v "x-workspace-id\|workspaceId"
```

---

## Phase 4: Integration Audit

Check how this module connects to other modules.

### Checks:

| # | Check | What to Look For | Pass Criteria |
|---|-------|-----------------|---------------|
| 4.1 | **Campaign → Training link** | Can campaigns auto-assign training on compromise? | `trainingId` on Campaign, `assignTrainingToCompromised` flag, TrainingTargets created with `campaignId` |
| 4.2 | **Training → Person credit** | Does training completion propagate to linked Persons? | `completionType: CROSS_WS_CREDIT` created for linked Recipients in other workspaces |
| 4.3 | **Announcement → Training link** | Can announcements auto-enroll in training on acknowledge? | `assignTrainingOnAck` + `trainingIdOnAck` fields on Announcement |
| 4.4 | **Portal shows all training types** | Does employee portal show Cards + Conversations + LMS Courses unified? | `/portal/trainings` endpoint merges TrainingTargets + CourseEnrollments |
| 4.5 | **Gamification cross-module** | Do points/badges work from campaigns, training, AND vishing? | PointTransaction records created from all three modules |
| 4.6 | **Risk score feeds from all modules** | Does recipient risk score include phishing + vishing + training data? | RiskScore calculation considers: campaign clicks, vishing compromises, training failures |
| 4.7 | **Company reports aggregate all modules** | Can CISO see unified dashboard across campaigns + training + vishing? | Company-level dashboard endpoint exists aggregating all modules |
| 4.8 | **JIT Coach triggers from all sources** | Can phishing clicks, vishing compromises, and weak passwords all trigger JIT tips? | JitTriggerRule supports PHISHING_CLICK, VISHING_COMPROMISE, WEAK_PASSWORD events |

### How to Check:
```bash
# Check cross-module FKs
grep -rn "campaignId\|trainingId\|announcementId\|vishingCampaignId" prisma/schema/

# Check if portal unifies training types
grep -rn "TrainingTargets\|CourseEnrollment" src/portal/
```

---

## Phase 5: Deployment & Migration Audit

Check operational readiness.

### Checks:

| # | Check | What to Look For | Pass Criteria |
|---|-------|-----------------|---------------|
| 5.1 | **Schema migration is non-breaking** | Do new columns have defaults or are nullable? | All new FKs (personId, blueprintId, companyId) are `String?` (nullable) |
| 5.2 | **Backfill job exists** | Is there a job to populate personId for existing recipients? | BullMQ job creates Person records for existing data |
| 5.3 | **Feature flags for progressive rollout** | Can UC3 features be enabled per company? | Feature flag or subscription tier check gates Blueprint/Library features |
| 5.4 | **Zero downtime deployment** | Can the migration run without taking the system down? | Additive schema changes only, no column renames or type changes |
| 5.5 | **Rollback safety** | Can new features be disabled without data loss? | `useCompanyDefaults: false` keeps workspace-level behavior unchanged |
| 5.6 | **Existing UC1 users unaffected** | Does a single-workspace customer see ANY change? | Zero visible UI changes for UC1 users after deployment |
| 5.7 | **Company Admin onboarding** | Is there a flow for setting up a new MSSP company? | Company creation → workspace creation → domain setup → admin invite flow exists |
| 5.8 | **Data isolation verification** | Has cross-workspace data leak been tested? | Workspace admin API tested with mismatched workspaceId — returns 403/empty |

---

## Report Template

After running all 5 phases, generate this report:

```markdown
# MSSP Audit Report: {Module Name}
Date: {date}
Auditor: {name}

## Executive Summary
- UC1 Readiness: {PASS / PARTIAL / FAIL} ({X}/{Y} checks passed)
- UC2 Readiness: {PASS / PARTIAL / FAIL} ({X}/{Y} checks passed)
- UC3 Readiness: {PASS / PARTIAL / FAIL} ({X}/{Y} checks passed)

## Phase 1: Data Model ({X}/10 passed)
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1.1 | workspaceId on every table | PASS/FAIL | {details} |
...

## Phase 2: API & Service ({X}/10 passed)
...

## Phase 3: Frontend ({X}/12 passed)
...

## Phase 4: Integration ({X}/8 passed)
...

## Phase 5: Deployment ({X}/8 passed)
...

## Critical Gaps (MUST fix before MSSP launch)
1. {gap} — Impact: {who is affected} — Effort: {sprints}
2. ...

## High Priority Gaps (should fix)
1. ...

## Recommended Migration Phases
Phase 1: {what} — {effort} — {no dependency}
Phase 2: {what} — {effort} — {depends on Phase 1}
...

## Risk Assessment
- Data leak risk: {LOW/MEDIUM/HIGH} — {why}
- User impact risk: {LOW/MEDIUM/HIGH} — {why}
- Rollback risk: {LOW/MEDIUM/HIGH} — {why}
```

## Scoring

**Per phase, count passed checks:**

| Phase | Total Checks | PASS threshold | CRITICAL threshold |
|-------|-------------|----------------|-------------------|
| Data Model | 10 | 8+ = PASS | <6 = CRITICAL |
| API & Service | 10 | 8+ = PASS | <6 = CRITICAL |
| Frontend | 12 | 9+ = PASS | <7 = CRITICAL |
| Integration | 8 | 6+ = PASS | <4 = CRITICAL |
| Deployment | 8 | 6+ = PASS | <4 = CRITICAL |

**Overall: Module is MSSP-ready only when ALL 5 phases score PASS.**

## Three Customer Type Validation

After the 48-check audit, validate against each customer type:

### UC1 Validation (must work WITHOUT multi-tenant features)
- [ ] Module works with 1 workspace, 1 domain, 1 admin
- [ ] No workspace selector shown
- [ ] No domain tabs shown
- [ ] No Person column shown
- [ ] No Company Library visible
- [ ] No Blueprint features visible
- [ ] No settings inheritance badges shown
- [ ] Performance acceptable (<2s page load for 1,500 records)

### UC2 Validation (must handle multiple domains in one workspace)
- [ ] Domain tabs shown when 2+ domains exist
- [ ] Person de-duplication works within workspace
- [ ] Bulk ops show domain breakdown
- [ ] Import assigns domain correctly
- [ ] Metrics show "unique persons" alongside "recipients"
- [ ] Person column shows link count

### UC3 Validation (must support full MSSP)
- [ ] Workspace selector works (switch context)
- [ ] Company Library accessible (scenarios, training, templates)
- [ ] Blueprint deployment creates workspace-specific records
- [ ] Company dashboard aggregates across workspaces
- [ ] Settings inheritance works (company default → workspace override)
- [ ] Person cross-workspace linking works
- [ ] Workspace isolation verified (no data leaks)
- [ ] Admin roles enforced (Company Admin vs Workspace Admin)

## How to Run an Audit — Step by Step

**Don't just read the checklist. Follow this exact sequence.**

### Step 1: Identify scope (5 min)
- What module? (Recipients, Campaigns, Training, Announcements, Vishing, Portal, Settings, JIT Coach)
- What codebase paths? (backend: `src/{module}/`, schema: `prisma/schema/{module}.prisma`, frontend: `features/{module}/` or `components/{module}/`)

### Step 2: Read the schema (15 min)
- Open every Prisma/Drizzle schema file for this module
- Run Phase 1 checks (1.1-1.10) while reading
- Note every table name, every FK, every index, every unique constraint
- **Tip:** `grep -n "model\|@@unique\|@@index\|workspaceId\|companyId\|personId" prisma/schema/{module}.prisma`

### Step 3: Read the controllers + services (20 min)
- Open every controller file — list every endpoint (method, path, guards)
- Open every service file — check every DB query for workspace scoping
- Run Phase 2 checks (2.1-2.10) while reading
- **Tip:** `grep -rn "findMany\|findFirst\|where:" src/{module}/ | grep -v "workspaceId"` — any hit = potential leak

### Step 4: Read the frontend (20 min)
- Open every page file for this module
- Check: how is data fetched? (React Query or raw fetch?)
- Check: is workspace header sent? Is domain filtering available?
- Run Phase 3 checks (3.1-3.12) while reading
- **Tip:** `grep -rn "limit=10000\|useEffect.*fetch\|useState.*\[\]" app/ components/ features/`

### Step 5: Check cross-module integration (10 min)
- Does this module connect to campaigns? Training? Portal? Gamification?
- Run Phase 4 checks (4.1-4.8) — these require reading SERVICE code, not just schema
- **Tip:** `grep -rn "campaignId\|trainingId\|vishingCampaignId" src/{module}/`

### Step 6: Check deployment readiness (10 min)
- Are new columns nullable? Is there a backfill job? Feature flags?
- Run Phase 5 checks (5.1-5.8)

### Step 7: Run negative tests (15 min)
See "Negative Test Patterns" below.

### Step 8: Generate report
Fill in the report template. Score each phase. List gaps by severity.

**Total time: ~90 minutes per module for a thorough audit.**

---

## Negative Test Patterns (CRITICAL — Catches Real Data Leaks)

These tests MUST be run. A passing checklist with failing negative tests = FALSE SENSE OF SECURITY.

### Test 1: Cross-Workspace Data Leak
```
SETUP: Two workspaces (WS-A, WS-B) with different data.
ACTION: Authenticate as WS-A admin. Call GET /api/{module} with x-workspace-id: WS-B.
EXPECTED: 403 Forbidden OR empty result set. NEVER return WS-B data.
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: If the API trusts the header without validating
user membership in that workspace, any authenticated user can see
any workspace's data by changing the header.
```

### Test 2: Bulk Operation Cross-Workspace
```
SETUP: WS-A has records [1,2,3]. WS-B has records [4,5,6].
ACTION: As WS-A admin, call POST /api/{module}/bulk-delete with ids: [1,4,5].
EXPECTED: Only record 1 deleted. Records 4,5 untouched (different workspace).
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: Bulk operations that don't include AND workspaceId = X
in the WHERE clause will delete/modify records across workspaces.
```

### Test 3: Company Admin Scope Boundary
```
SETUP: Company admin with access to WS-A and WS-B.
ACTION: Call company-level endpoint GET /companies/{id}/reports.
EXPECTED: Aggregated data from BOTH workspaces.
ACTION 2: Same admin, call workspace endpoint GET /api/{module} with x-workspace-id: WS-A.
EXPECTED: Only WS-A data. NOT aggregated.
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: Company endpoints aggregate. Workspace endpoints isolate.
Mixing them up = data leak or missing data.
```

### Test 4: Person De-Duplication
```
SETUP: Vikram exists in domain-A (vikram@jio.com) and domain-B (vikram@jiosaavn.com).
       Both linked to same Person.
ACTION: Create campaign targeting "all users" with deduplicateByPerson: true.
EXPECTED: Vikram appears as 1 target (primary email), not 2.
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: Without Person de-dup, Vikram gets 2 phishing emails,
2 training enrollments, and inflates all metrics by 2x.
```

### Test 5: UC1 Progressive Complexity
```
SETUP: Company with 1 workspace, 1 domain.
ACTION: Load the module's main page as workspace admin.
EXPECTED: No workspace selector. No domain tabs. No Person column.
          No Company Library. No Blueprint features. Clean simple UI.
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: If UC1 users see UC3 complexity, they're confused
and think the product is hard to use. Progressive complexity is not optional.
```

### Test 6: Settings Inheritance
```
SETUP: Company default: trackOpens=true. WS-A inherits. WS-B overrides to false.
ACTION: GET /api/settings for WS-A.
EXPECTED: trackOpens=true (inherited), source="company".
ACTION 2: GET /api/settings for WS-B.
EXPECTED: trackOpens=false (overridden), source="override".
ACTION 3: Company admin changes default to false.
ACTION 4: GET /api/settings for WS-A again.
EXPECTED: trackOpens=false (inherited updated). WS-B still false (override unchanged).
ACTUAL: ___
PASS/FAIL: ___

WHY THIS MATTERS: Settings inheritance with overrides is subtle.
If the resolution algorithm is wrong, changing company defaults either
doesn't propagate or overwrites workspace overrides.
```

---

## Planning Phase Enforcement

**Before building ANY new feature, these questions MUST be answered.**

### Mandatory Planning Questions (block code if unanswered)

| # | Question | If You Don't Know → | Skill Reference |
|---|----------|-------------------|-----------------|
| 1 | **Which customer types are affected?** (UC1 / UC2 / UC3 / all) | Review the 3 customer profiles in `saas-architect-skill/mssp-patterns.md` | SaaS: mssp-patterns.md → "Three Customer Types" |
| 2 | **Which hierarchy level owns this data?** (Company / Workspace / Domain) | Check the tenant hierarchy in SaaS skill | SaaS: SKILL.md → "Tenant Hierarchy" |
| 3 | **Does this need a Company Library tier?** | If the content could be shared across workspaces, yes | SaaS: mssp-patterns.md → "Company Library Pattern" |
| 4 | **Does this need a Blueprint pattern?** | If CISO would want to deploy once to all subsidiaries, yes | SaaS: mssp-patterns.md → "Blueprint Pattern" |
| 5 | **Does this touch Person/Recipient?** | If targeting people, always check de-dup needs | SaaS: mssp-patterns.md → "Person / Linked Identity Pattern" |
| 6 | **What settings are configurable?** | List every setting. Mark which inherit, which are workspace-specific | SaaS: mssp-patterns.md → "Settings Inheritance Pattern" |
| 7 | **Who can do what?** | Fill in the permission matrix for this feature | SaaS: mssp-patterns.md → "Admin Role Pattern" → permission matrix |
| 8 | **What does UC1 user see?** | Apply progressive complexity rule | Frontend: SKILL.md → "Progressive Complexity Rule" |
| 9 | **What does the audit checklist say?** | Run the 48-check audit BEFORE coding | This skill → Phases 1-5 |
| 10 | **What's the migration path?** | Non-breaking? Feature flag? Backfill? | SaaS: SKILL.md → Phase 2 (schema) + this skill → Phase 5 (deployment) |

**If any answer is "I don't know" → STOP. Read the referenced skill section. Then answer. Then code.**

### Planning Output Template

Before writing any code, produce this document:

```markdown
# Feature Plan: {name}

## Answers to 10 Questions
1. Customer types: {UC1/UC2/UC3/all}
2. Hierarchy level: {Company/Workspace/Domain}
3. Company Library: {yes/no — why}
4. Blueprint: {yes/no — why}
5. Person/Recipient: {yes/no — de-dup needed?}
6. Settings: {list fields, mark inheritable vs workspace-specific}
7. Permissions: {table: action × role}
8. UC1 view: {what's hidden}
9. Audit pre-check: {which phases/checks apply}
10. Migration: {schema changes, feature flags, backfill}

## Backend Design (from SaaS skill Phase 1-7)
- Schema: {tables, FKs, indexes}
- Endpoints: {list}
- Async: {which operations need BullMQ}

## Frontend Design (from Frontend skill Phase 0-6)
- Types: {entities, filters, form schemas}
- Components: {data table, form, detail, wizard}
- State: {React Query keys, any Zustand stores}

## Risks
- Data leak risk: {assessment}
- UC1 impact: {assessment}
- Migration risk: {assessment}
```

**This document is the GATE. No code without this document.**
