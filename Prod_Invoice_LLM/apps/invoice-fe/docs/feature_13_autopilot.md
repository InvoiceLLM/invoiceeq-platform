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
- **Unified Logic:** The scheduled job and manual "Sync Now" button call the exact same backend sync processor function (`POST /api/v1/invoices/sync`).

---

## Tasks

- [ ] **Task 13.1: DB Schema Migration** — Generate Alembic migrations for the `tenant_autopilot_configs` and `tenant_autopilot_logs` tables.
- [ ] **Task 13.2: Unified Ingestion Service** — Implement the shared entrypoint function in backend. It queries new files, runs dedup checks, downloads bytes, saves to Blob Storage, dispatches queue extraction, and logs outcomes.
- [ ] **Task 13.3: Sync API Endpoints** — Create the backend router endpoints:
  - `POST /api/v1/invoices/sync` (shared trigger endpoint)
  - `GET/PUT /api/v1/autopilot/config` (configuration manager)
  - `GET /api/v1/autopilot/history` (runs log)
- [ ] **Task 13.4: Azure Container Apps Job** — Configure a Bicep deployment for an ACA Job pointing to the `/sync` CLI script.
- [ ] **Task 13.5: Folder Picker API** — Connect Google Drive Picker and Salesforce API folders list to frontend browse modals.
- [ ] **Task 13.6: Enhanced Settings UI** — Build the Next.js Autopilot Settings and Ingestion screen (`/ingestion`) combining the config form, custom picker, manual upload zone, and runs table.
