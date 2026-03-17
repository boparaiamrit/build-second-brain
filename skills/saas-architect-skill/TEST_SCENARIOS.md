# Skill Evaluation — 5 Test Scenarios

---

## TEST 1: Simple Recipient List Page (Tests: hierarchy enforcement, N+1, pagination)

**Frontend code given:**
```tsx
// RecipientTable.tsx
const RecipientTable = () => {
  const { data } = useQuery(['recipients'], () => api.get('/recipients'));
  return (
    <table>
      {data.map(r => (
        <tr key={r.id}>
          <td>{r.email}</td>
          <td>{r.name}</td>
          <td>{r.emailStatus}</td>  {/* from email extension */}
          <td>{r.phone}</td>         {/* from sms extension */}
          <td>{r.customFields.industry}</td>
        </tr>
      ))}
    </table>
  );
};
```

**Expected skill output should catch:**
- [ ] Route must be scoped: `GET /domains/:domainId/recipients` (not `/recipients`)
- [ ] domainId is the primary filter (hot path)
- [ ] N+1 risk: emailStatus comes from email_recipients, phone from sms_recipients
- [ ] Must LEFT JOIN or batch IN to get extension data — not loop query
- [ ] Custom field filtering needs GIN index
- [ ] Must be paginated (meta with total, hasMore)
- [ ] TenantContextGuard resolves company/workspace from Redis
- [ ] Subscription limit check before returning data

---

## TEST 2: Bulk Select All (Tests: async pattern, >1000 rule, job queue, SSE)

**Frontend code given:**
```tsx
// BulkActions.tsx
const handleSelectAll = async () => {
  const result = await api.post('/recipients/bulk-select', {
    filter: { status: 'active', customFields: { industry: 'tech' } }
  });
  if (result.jobId) {
    // Subscribe to SSE for progress
    const es = new EventSource(`/jobs/${result.jobId}/progress`);
    es.onmessage = (e) => setProgress(JSON.parse(e.data));
  }
};
```

**Expected skill output should catch:**
- [ ] Route: `POST /domains/:domainId/recipients/bulk-select`
- [ ] Service counts affected rows FIRST
- [ ] If >1000 → BullMQ job, return { jobId, status: 'queued' }
- [ ] If ≤1000 → synchronous, return { affected, status: 'completed' }
- [ ] Processor extends BaseProcessor
- [ ] Redis progress key: `job:{jobId}:progress` updated every batch
- [ ] SSE endpoint: `GET /domains/:domainId/jobs/:jobId/progress`
- [ ] Job deduplication: `jobId: bulk-select:${domainId}`
- [ ] @Audit('recipient.bulk_select') decorator
- [ ] Custom field filter uses JSONB query with GIN index

---

## TEST 3: CSV Import (Tests: staging table, preview, commit, file handling)

**Frontend code given:**
```tsx
// ImportRecipients.tsx
const handleUpload = async (file: File) => {
  const { uploadUrl, jobId } = await api.post('/recipients/imports/upload-url');
  await fetch(uploadUrl, { method: 'PUT', body: file });
  await api.post(`/recipients/imports/${jobId}/process`);
  
  // Wait for validation
  const preview = await api.get(`/recipients/imports/${jobId}/preview`);
  setPreview(preview); // { validRows: 45000, errorRows: 312, sampleErrors: [...] }
  
  if (userConfirms) {
    await api.post(`/recipients/imports/${jobId}/commit`);
    // SSE progress until done
  }
};
```

**Expected skill output should catch:**
- [ ] Route hierarchy: `/domains/:domainId/recipients/imports/...`
- [ ] Presigned S3 URL for upload (never through our server)
- [ ] importJobs table with status flow: pending→validating→preview→processing→done|failed
- [ ] importStagingRows table for validation
- [ ] Validate against workspace custom_field_definitions (cached from Redis)
- [ ] Preview endpoint returns sampleData + sampleErrors
- [ ] Commit moves valid rows from staging → recipients
- [ ] ON CONFLICT (domain_id, email) DO UPDATE for duplicates
- [ ] company_id, workspace_id, domain_id populated from tenantContext
- [ ] Plan limit check: PlanStrategy.maxRecipientsPerImport()
- [ ] Two processors: ImportValidationProcessor + ImportCommitProcessor
- [ ] Both extend BaseProcessor → auto job_logs
- [ ] @Audit('recipient.import_started') + @Audit('recipient.import_committed')
- [ ] Subscription enforcement: total recipients + imported ≤ recipientLimit

---

## TEST 4: SSO Setup (Tests: adapter pattern, manager, enterprise-only, research)

**Frontend code given:**
```tsx
// SsoSettings.tsx
const SsoSetup = () => {
  const [provider, setProvider] = useState<'microsoft_ad' | 'google' | 'okta'>('microsoft_ad');
  
  const handleSave = async (config) => {
    await api.post(`/workspaces/${wsId}/sso/connections`, { provider, ...config });
  };
  
  const handleTest = async () => {
    const { authUrl } = await api.get(`/workspaces/${wsId}/sso/login`);
    window.location.href = authUrl;
  };
  
  const handleSync = async () => {
    const { jobId } = await api.post(`/workspaces/${wsId}/sso/sync`);
    // Track progress...
  };
};
```

**Expected skill output should catch:**
- [ ] Plan check: PlanStrategy.canUseSSO() — enterprise only
- [ ] Route at workspace level: `/workspaces/:workspaceId/sso/...`
- [ ] Adapter pattern: IdentityAdapter interface
- [ ] Manager pattern: IdentityManager.forProvider()
- [ ] Research template filled for chosen provider's library
- [ ] Token refresh handling with 5min buffer
- [ ] Directory sync runs as BullMQ job (not synchronous)
- [ ] Pagination to completion in background
- [ ] Job deduplication: `active_job:${workspaceId}:identity-sync`
- [ ] SSO connection config stored with encrypted tokens
- [ ] @Audit on every SSO action
- [ ] Webhook validation if provider supports it

---

## TEST 5: Cross-Domain Dashboard (Tests: workspace-level query, TimescaleDB, no domain pivot)

**Frontend code given:**
```tsx
// WorkspaceDashboard.tsx
const Dashboard = () => {
  const { data: stats } = useQuery(['ws-stats'], () =>
    api.get(`/workspaces/${wsId}/dashboard/stats`)
  );
  // stats = {
  //   totalRecipients: 245000,
  //   recipientsByDomain: [{ domain: 'a.com', count: 120000 }, ...],
  //   emailsSentThisMonth: 1200000,
  //   openRate: 0.34,
  //   bounceRate: 0.02,
  //   topCampaigns: [...],
  // }
};
```

**Expected skill output should catch:**
- [ ] Route at workspace level: `/workspaces/:workspaceId/dashboard/stats`
- [ ] Recipient counts: query recipients WHERE workspace_id (NOT domain_id)
- [ ] workspace_id index needed: add idx_recipients_workspace (Phase 2 proven pattern)
- [ ] Email stats from TimescaleDB continuous aggregate (email_daily_stats)
- [ ] Query: WHERE workspace_id AND time > start_of_month
- [ ] NO joins through domains table — direct workspace_id filter
- [ ] Cache result in Redis: `workspace:{wsId}:dashboard:{date}` TTL 5min
- [ ] This is a READ-only reporting endpoint — no audit needed
- [ ] tenantContext still needed for subscription check
- [ ] company_id available for billing usage queries if needed
