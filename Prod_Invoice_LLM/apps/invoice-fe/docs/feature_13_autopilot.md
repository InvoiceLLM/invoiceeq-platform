# Feature 13: Tenant Autopilot — upgrade Ingest & Scheduled Sync

> **⚠️ Salesforce — removed 2026-08-28, see Gap 334 (BE) / Gap 322 (FE).** Google Drive is now
> the only connector. Salesforce references below are struck through or annotated and kept as
> historical record, not deleted. Two independent causes: (1) the OAuth app is a Salesforce
> **External Client App** with **Distribution State = Local**, which structurally blocks cross-org
> OAuth — confirmed live against `ca-invoice-be-dev` with Salesforce's own
> `OAUTH_AUTHORIZATION_BLOCKED — Cross-org OAuth flows are not supported for this external client
> app`, unfixable by any setting (new classic Connected Apps were also blocked as of Spring '26);
> (2) wrong data model — the connector browsed Salesforce **Libraries** (`ContentWorkspace`), but
> real invoices live on **Account/Opportunity** records.


**Extends Feature 3** (`feature_3_ingestion.md`). Autopilot is a unified portal combining manual invoice upload, scheduled sync configurations (Google Drive), and automated deduplication.

## Product & Technical Scope

### 1. Settings & Sync Interface (Single Page)
Autopilot is implemented on the Ingestion screen (`/ingestion`) and provides:
- **Option A (Manual File Upload):** A drag-and-drop zone to upload local invoice PDFs manually.
- **Option B (Bulk Sync from Cloud):** A folder selection field with a **"Browse"** button (to select custom Drive folders) and a **"Sync Now"** button for immediate trigger.
- **Automation Configuration Form:** ~~Select and set a single sync source (Google Drive or Salesforce — not both simultaneously)~~ **— the "Cloud Source" toggle was removed 2026-08-28 (FE Gap 322): with Salesforce gone it would render one always-selected button that does nothing. `source_type` stays pinned to `'gdrive'`.** Set flow direction (Inbound AP vs Outbound AR), scheduling cron/interval, notification emails, and manual audit approval link options.
- **Recent Runs & Sync History Table:** A unified log list showing execution runs (Manual / Scheduled), source type, files processed, skipped duplicate count, and success/failed status outcomes.

---

### 2. Database Schema

#### Table: `tenant_autopilot_configs`
Stores folder synchronization and automation settings per tenant workspace.
```sql
CREATE TABLE tenant_autopilot_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    source_type VARCHAR(50) NOT NULL, -- 'gdrive' | 'email'  ('salesforce' removed 2026-08-28, Gap 334)
    source_ref VARCHAR(1024) NOT NULL, -- Drive Folder ID
    flow_direction VARCHAR(10) NOT NULL DEFAULT 'INBOUND', -- 'INBOUND' | 'OUTBOUND'
    trigger_mode VARCHAR(20) NOT NULL, -- 'interval' | 'cron'
    trigger_value VARCHAR(100) NOT NULL, -- cron expression (e.g. '0 * * * *') or interval in minutes
    notify_emails JSONB NOT NULL DEFAULT '[]', -- array of email recipient strings
    send_approval_links BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_autopilot_config_tenant ON tenant_autopilot_configs(tenant_id);
```

#### Table: `tenant_autopilot_logs`
Deduplication ledger tracking all processed files to prevent duplicate ingestion.
```sql
CREATE TABLE tenant_autopilot_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    source_type VARCHAR(50) NOT NULL, -- 'gdrive' | 'email' | 'manual'  ('salesforce' removed 2026-08-28, Gap 334)
    source_file_id VARCHAR(255) NOT NULL, -- Google Drive fileId
    content_hash VARCHAR(64) NOT NULL, -- SHA-256 hash of document content
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(50) NOT NULL -- 'SUCCESS' | 'SKIPPED_DUPLICATE' | 'FAILED'
);
CREATE INDEX idx_autopilot_log_tenant_file ON tenant_autopilot_logs(tenant_id, source_file_id);
CREATE INDEX idx_autopilot_log_hash ON tenant_autopilot_logs(content_hash);
```

---

### 3. Deduplication & Sync Mechanics
- **Incremental Polling:** Sync operations only fetch files created or modified after the timestamp of the last successful run (`ingested_at` of the last successful config execution).
- **Two-Layer Deduplication:**
  1. Check if `source_file_id` exists in `tenant_autopilot_logs` for the tenant. If yes, skip.
  2. Check if `content_hash` exists in `tenant_autopilot_logs` for the tenant (reuses existing email attachment deduplication hash logic). If yes, skip and log as `SKIPPED_DUPLICATE`.

---

### 4. Trigger Mechanism
- **Azure Container Apps Job:** Synchronizer is scheduled and triggered via Azure Container Apps Jobs (cron-based), **NOT** Celery beat.
- **Unified Logic:** The scheduled job and manual "Sync Now" button call the exact same backend sync processor function (`POST /api/v1/invoices/sync`).

---

## Tasks

- [x] **Task 13.1: DB Schema Migration** — Generate Alembic migration `add_autopilot_tables` for the `tenant_autopilot_configs` and `tenant_autopilot_logs` tables.
- [x] **Task 13.2: Unified Ingestion Service** — Implement `services/autopilot_sync.py` shared sync engine (incremental polling, two-layer dedup, Azure Blob Storage upload, Queue dispatch, and log creation).
- [x] **Task 13.3: Sync API Endpoints** — Create backend router `routers/autopilot.py`:
  - `POST /api/v1/autopilot/sync` (shared trigger endpoint)
  - `GET /api/v1/autopilot/config` & `PUT /api/v1/autopilot/config` (configuration manager)
  - `GET /api/v1/autopilot/history` (paginated runs log)
- [ ] **Task 13.4: Azure Container Apps Job Bicep IaC** — Script `scripts/autopilot_job.py` built; Bicep IaC module deferred for production deployment.
- [x] **Task 13.5: Folder Picker Integration** — Connected folder browsing with ConnectorBrowseBar pattern. *(FE Gap 219, Aug 12, 2026: Autopilot config tab `source_ref` field now uses read-only folder name + Browse → `FolderTreeExplorer` with `selectionMode="folder"`; locked when connector inactive. `e2e/autopilot-folder-browser.spec.ts`.)*
- [x] **Task 13.6: Autopilot UI & Sync History Table** — Built `AutopilotHistoryTable.tsx` component and Autopilot tab + config form on `/ingestion` screen.
- [x] **Task 13.7: Automated Pytest Suite** — Created `tests/test_autopilot.py` with 18 unit/integration tests (100% pass rate). *(BE Gap 220, Aug 12, 2026: `test_T19_autopilot_sends_notify_email_after_import` — notify summary email with review deep links after sync; live SendGrid still Gap 125.)*

### Recent Fixes (Aug 12, 2026)
* **FE Gap 219 — Autopilot folder browser**: Autopilot config `source_ref` is no longer a raw ID text field. Read-only folder name + **Browse →** opens `FolderTreeExplorer` in `selectionMode="folder"`; inactive connectors show **Connect in Settings**.
* **BE Gap 220 — notification emails after sync**: `services/autopilot_sync.py::run_sync()` collects newly imported invoices and calls `services/staff_notify.notify_autopilot_sync_summary()` when `notify_emails` is non-empty and `processed > 0`. Review deep links (`/invoices/review/{id}`) are included when `send_approval_links=True`. SendGrid missing → log warning, sync still succeeds. Live mail still depends on Gap 125.

### Recent Fixes (Aug 23, 2026)
* **FE Gap 288 — "Sync Now" could sync a stale folder**: picking a folder in `FolderTreeExplorer` (Gap 219's Browse flow) only ever updated local `autopilotConfig` React state — it never called `PUT /autopilot/config`. Clicking **Sync Now** without first clicking **Save Config** therefore synced whatever `source_ref` was already persisted, not the folder just picked on screen. `handleSyncNow` (`app/ingestion/page.tsx`) now saves the current config immediately before triggering sync, so Sync Now always acts on what's shown in the UI. Also fixed: the generic `"Sync failed. Please check your configuration."` fallback couldn't distinguish a real backend error from a request that never got a clean response at all (network failure, non-JSON body) — `describeAutopilotError()` now surfaces the HTTP status when there is a response, or the underlying network error when there isn't, instead of one uninformative string either way.

### Recent Fixes (Aug 28, 2026)
* **FE Gap 321 — Missing Next.js API Route Proxy Handlers for Autopilot**: While `app/ingestion/page.tsx` used `apiClient` (which calls `/api/autopilot/*`), the Next.js backend proxy route handlers under `app/api/autopilot/` were missing, causing browser calls to fail with `HTTP 404 (Not Found)`. Added `app/api/autopilot/config/route.ts` (GET & PUT), `app/api/autopilot/sync/route.ts` (POST), and `app/api/autopilot/history/route.ts` (GET) delegating to FastAPI `/api/v1/autopilot/*` via `proxyJson()`. Type-checked (`npx tsc --noEmit`), E2E tested (`e2e/autopilot-folder-browser.spec.ts` passing), and backend verified (`pytest tests/test_autopilot.py` 19/19 passing).

