# Feature 13: Tenant Autopilot — upgrade Ingest & Scheduled Sync

**Extends Feature 3** (`feature_3_ingestion.md`). Autopilot is a unified portal combining manual invoice upload, scheduled sync configurations (Google Drive or Salesforce), and automated deduplication.

## Product & Technical Scope

### 1. Settings & Sync Interface (Single Page)
Autopilot is implemented on the Ingestion screen (`/ingestion`) and provides:
- **Option A (Manual File Upload):** A drag-and-drop zone to upload local invoice PDFs manually.
- **Option B (Bulk Sync from Cloud):** A folder selection field with a **"Browse"** button (to select custom Drive folders or Salesforce directories) and a **"Sync Now"** button for immediate trigger.
- **Automation Configuration Form:** Select and set a single sync source (Google Drive or Salesforce — not both simultaneously), flow direction (Inbound AP vs Outbound AR), scheduling cron/interval, notification emails, and manual audit approval link options.
- **Recent Runs & Sync History Table:** A unified log list showing execution runs (Manual / Scheduled), source type, files processed, skipped duplicate count, and success/failed status outcomes.

---

### 2. Database Schema

#### Table: `tenant_autopilot_configs`
Stores folder synchronization and automation settings per tenant workspace.
```sql
CREATE TABLE tenant_autopilot_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    source_type VARCHAR(50) NOT NULL, -- 'gdrive' | 'salesforce' | 'email'
    source_ref VARCHAR(1024) NOT NULL, -- Drive Folder ID / Salesforce Directory ID
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
    source_type VARCHAR(50) NOT NULL, -- 'gdrive' | 'salesforce' | 'email' | 'manual'
    source_file_id VARCHAR(255) NOT NULL, -- Google Drive fileId or Salesforce record ID
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
- **Unified Logic:** The scheduled job and manual "Sync Now" button call the exact same backend sync processor function (`POST /api/v1/autopilot/sync`). *(Corrected 2026-08-21 — this line previously read `/api/v1/invoices/sync`, an endpoint that does not exist; the real path is and always was `/api/v1/autopilot/sync` per `routers/autopilot.py`.)*

---

### 5. Frontend ↔ Backend Wiring (added 2026-08-21 — FE Gap 278)

**This section did not exist until the omission it describes had already shipped and broken the feature in production.** It is written as a requirement, not a note, because its absence is the entire reason Autopilot never worked from a browser.

The backend endpoints in section 3 are **not reachable from the browser on their own.** `lib/apiClient.ts` is same-origin (`baseURL: "/api"`) and `invoice-fe/next.config.js` defines **no `rewrites()`** — only `assetPrefix`. There is no catch-all forwarding `/api/*` to FastAPI. In Azure the backend Container App additionally runs with `ingress.external: false`, so the browser could not reach it directly even if the origin were known.

Therefore **every** backend endpoint this feature exposes requires a matching Next.js Route Handler under `app/api/**`, each a thin `proxyJson()` pass-through:

| Browser calls | Route Handler | Proxies to |
|---|---|---|
| `GET/PUT /api/autopilot/config` | `app/api/autopilot/config/route.ts` | `/autopilot/config` |
| `POST /api/autopilot/sync` | `app/api/autopilot/sync/route.ts` | `/autopilot/sync` |
| `GET /api/autopilot/history` | `app/api/autopilot/history/route.ts` | `/autopilot/history` |

Without these, calls 404 at Next.js and never reach FastAPI — and the failure is **near-silent**, because a Next 404 returns HTML, so `err.response.data.detail` is `undefined` and callers fall back to generic messages that blame the user's configuration. The Autopilot tab rendered normally with default values the whole time.

**Rule for any future connector or backend-backed feature in this app: a backend endpoint without a corresponding `app/api/**` Route Handler is not shipped, and no test that drives FastAPI through `TestClient` can detect its absence** — the backend suite passes identically whether the proxy routes exist or not.

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
- [x] **Task 13.7: Automated Pytest Suite** — Created `tests/test_autopilot.py`, now **21** unit/integration tests (100% pass rate). *(BE Gap 220, Aug 12, 2026: `test_T19_autopilot_sends_notify_email_after_import` — notify summary email with review deep links after sync; live SendGrid still Gap 125.)* *(BE Gap 288, Aug 21, 2026: +`test_T12b`/`test_T12c`; `_make_connection()` fixture default corrected. **Caveat worth carrying forward** — this suite was 100% green for nine days while Google Drive sync was completely broken in production, because the fixture reproduced the bug and because `TestClient` bypasses Next.js entirely. Pass rate here is evidence about the sync engine, not about the feature working.)*
- [x] **Task 13.8: Frontend API Proxy Routes** — `app/api/autopilot/{config,sync,history}/route.ts`. **Retro-added 2026-08-21 (FE Gap 278): this task was never written down, and so was never built** — see section 5. The feature was marked complete on 2026-08-12 without it, and no Autopilot call from the browser had ever reached the backend until this shipped.

### Recent Fixes (Aug 21, 2026)
* **FE Gap 278 — Autopilot proxy routes were never built**: added the three `app/api/autopilot/**` Route Handlers and, more importantly, wrote section 5 above so the requirement is specified rather than assumed. Verified live by differential comparison against known-good and known-missing routes with auth bypassed — see `docs/test_coverage_map.md`, including why an unauthenticated 404 proves nothing on this app (Clerk's `auth().protect()` answers unauthenticated API requests with 404, not 401).
* **BE Gap 288 — Google Drive sync never matched its OAuth connection**: `services/autopilot_sync.py::run_sync()` compared `TenantConnection.provider` against `TenantAutopilotConfig.source_type` directly, but Autopilot spells it `gdrive` while Connectors persists `google_drive`. Fixed with an explicit `SOURCE_TYPE_TO_PROVIDER` mapping; unknown `source_type` now raises a distinct config error rather than reporting "not connected". Affected the scheduled ACA job as well as the manual button. **Mutation-checked**: re-introducing the bug fails 7 tests. Salesforce was never affected — it is spelled identically in both vocabularies.
* **Still open after both fixes**: no Autopilot sync has yet been run end-to-end against a real Google Drive account with a live OAuth token. Everything above proves the plumbing connects and the lookup resolves; none of it proves an invoice actually moves from Drive into the system.

### Recent Fixes (Aug 12, 2026)
* **FE Gap 219 — Autopilot folder browser**: Autopilot config `source_ref` is no longer a raw ID text field. Read-only folder name + **Browse →** opens `FolderTreeExplorer` in `selectionMode="folder"`; inactive connectors show **Connect in Settings**.
* **BE Gap 220 — notification emails after sync**: `services/autopilot_sync.py::run_sync()` collects newly imported invoices and calls `services/staff_notify.notify_autopilot_sync_summary()` when `notify_emails` is non-empty and `processed > 0`. Review deep links (`/invoices/review/{id}`) are included when `send_approval_links=True`. SendGrid missing → log warning, sync still succeeds. Live mail still depends on Gap 125.

