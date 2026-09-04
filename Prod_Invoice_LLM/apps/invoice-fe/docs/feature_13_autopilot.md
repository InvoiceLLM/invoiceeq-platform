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
  - `GET /api/v1/autopilot/history` (paginated runs log — per-run summaries as of BE Gap 427)
  - `GET /api/v1/autopilot/history/{batch_id}/files` (per-run file drill-down; `legacy` bucket for pre-Gap-427 rows — BE Gap 427)
  - `DELETE /api/v1/autopilot/history/{batch_id}` (dismiss one run) and `DELETE /api/v1/autopilot/history` (hide all) — BE Gap 429
  - `history_retention_days` on GET/PUT `/api/v1/autopilot/config` (7–365, default 90) — BE Gap 429
- [ ] **Task 13.4: Azure Container Apps Job Bicep IaC** — Script `scripts/autopilot_job.py` built; Bicep IaC module deferred for production deployment.
- [x] **Task 13.5: Folder Picker Integration** — Connected folder browsing with ConnectorBrowseBar pattern. *(FE Gap 219, Aug 12, 2026: Autopilot config tab `source_ref` field now uses read-only folder name + Browse → `FolderTreeExplorer` with `selectionMode="folder"`; locked when connector inactive. `e2e/autopilot-folder-browser.spec.ts`.)*
- [x] **Task 13.6: Autopilot UI & Sync History Table** — Built `AutopilotHistoryTable.tsx` component and Autopilot tab + config form on `/ingestion` screen. *(FE Gap 428, Sep 4, 2026: rewritten from one row per file to one row per run — summary tiles, sentence rows, proportional bar, lazily fetched per-run file drill-down, new `app/api/autopilot/history/[batchId]/files/route.ts` proxy. See Recent Fixes below.)* *(FE Gap 434, Sep 4, 2026: per-run dismiss, clear-all with inline confirm, retention footnote, `history_retention_days` in the config form, new `app/api/autopilot/history/[batchId]/route.ts` DELETE proxy.)*
- [x] **Task 13.7: Automated Pytest Suite** — Created `tests/test_autopilot.py` with 18 unit/integration tests (100% pass rate). *(BE Gap 220, Aug 12, 2026: `test_T19_autopilot_sends_notify_email_after_import` — notify summary email with review deep links after sync; live SendGrid still Gap 125.)*

### Recent Fixes (Aug 12, 2026)
* **FE Gap 219 — Autopilot folder browser**: Autopilot config `source_ref` is no longer a raw ID text field. Read-only folder name + **Browse →** opens `FolderTreeExplorer` in `selectionMode="folder"`; inactive connectors show **Connect in Settings**.
* **BE Gap 220 — notification emails after sync**: `services/autopilot_sync.py::run_sync()` collects newly imported invoices and calls `services/staff_notify.notify_autopilot_sync_summary()` when `notify_emails` is non-empty and `processed > 0`. Review deep links (`/invoices/review/{id}`) are included when `send_approval_links=True`. SendGrid missing → log warning, sync still succeeds. Live mail still depends on Gap 125.

### Recent Fixes (Aug 23, 2026)
* **FE Gap 288 — "Sync Now" could sync a stale folder**: picking a folder in `FolderTreeExplorer` (Gap 219's Browse flow) only ever updated local `autopilotConfig` React state — it never called `PUT /autopilot/config`. Clicking **Sync Now** without first clicking **Save Config** therefore synced whatever `source_ref` was already persisted, not the folder just picked on screen. `handleSyncNow` (`app/ingestion/page.tsx`) now saves the current config immediately before triggering sync, so Sync Now always acts on what's shown in the UI. Also fixed: the generic `"Sync failed. Please check your configuration."` fallback couldn't distinguish a real backend error from a request that never got a clean response at all (network failure, non-JSON body) — `describeAutopilotError()` now surfaces the HTTP status when there is a response, or the underlying network error when there isn't, instead of one uninformative string either way.

### Recent Fixes (Aug 28, 2026)
* **FE Gap 321 — Missing Next.js API Route Proxy Handlers for Autopilot**: While `app/ingestion/page.tsx` used `apiClient` (which calls `/api/autopilot/*`), the Next.js backend proxy route handlers under `app/api/autopilot/` were missing, causing browser calls to fail with `HTTP 404 (Not Found)`. Added `app/api/autopilot/config/route.ts` (GET & PUT), `app/api/autopilot/sync/route.ts` (POST), and `app/api/autopilot/history/route.ts` (GET) delegating to FastAPI `/api/v1/autopilot/*` via `proxyJson()`. Type-checked (`npx tsc --noEmit`), E2E tested (`e2e/autopilot-folder-browser.spec.ts` passing), and backend verified (`pytest tests/test_autopilot.py` 19/19 passing).


### Recent Fixes (Sep 4, 2026)
* **FE Gap 428 — Sync History rewritten from a per-file table to a per-run summary with drill-down** (paired with BE Gap 427, which supplies the new endpoints). Before this change `components/ingestion/AutopilotHistoryTable.tsx` rendered one flat row per *file* — Date / Source / raw Drive **File ID** / Status / Detail — so a 14-file sync read as 14 unrelated lines of opaque ids and no run ever had a visible outcome. It now renders one row per **run**.

  **Backend contract consumed** (BE Gap 427, coded against, not waited on):
  - `GET /api/autopilot/history?page=&page_size=` → `{ items: Run[], total, page, page_size }` where `Run = { batch_id, trigger, source_type, started_at, finished_at, files_seen, imported, skipped, failed, status }` and `status ∈ SUCCESS | PARTIAL | FAILED | NO_NEW_FILES`.
  - `GET /api/autopilot/history/{batch_id}/files` → `{ items: [{ id, source_file_id, source_file_name, content_hash, ingested_at, status, error_detail }] }`.
  - `batch_id: null` is the single legacy bucket for pre-Gap-427 rows. It is rendered as **“Earlier activity”** (no date/trigger lead-in, since neither is meaningful for a bucket), and its files are fetched from the `legacy` path — `runKey()` maps `null → "legacy"`, which is both the React key and the URL segment.

  **New proxy route.** `app/api/autopilot/history/[batchId]/files/route.ts` — `GET`, mirrors the sibling `history/route.ts`: `proxyJson(request, "/autopilot/history/{batchId}/files")` with `dynamic = "force-dynamic"` and `encodeURIComponent` on the segment. Same `[param]` handler shape as `app/api/audit/resolve/[id]/route.ts`.

  **Component structure** (export name `AutopilotHistoryTable` and the `autoRefresh` prop are unchanged, so `app/ingestion/page.tsx`’s call site was not touched):
  - **Header strip, three tiles** via `SummaryTile` — *Last run* (`relativeTime()` + a `RunStatusChip`), *Imported (last 7 days, loaded runs)* (summed over the runs on the currently loaded page only — the label states that limit rather than implying a tenant-wide total the endpoint does not return), and *Sync* (spinner + “In progress…” when `autoRefresh` is true, otherwise “Idle”).
  - **Run row reads as a sentence** — `formatRunTime()` (“Today 09:12” / “Yesterday 17:40” / “12 Aug 09:12”) · `triggerLabel()` (Manual / Scheduled / Autopilot when null) · `sourceLabel()` (Gap 322’s gdrive→“Google Drive”, everything else “Manual”) · `runSummarySentence()` (“14 files: 11 imported, 2 skipped, 1 failed”; zero-count clauses are dropped, and a `NO_NEW_FILES` run with `files_seen === 0` reads “No new files”).
  - **`RunStatusChip`** — SUCCESS emerald, PARTIAL amber, FAILED rose, NO_NEW_FILES slate “Nothing new”; same pill geometry as the existing `StatusBadge`.
  - **`RunProportionBar`** — a 1px-tall proportional imported/skipped/failed bar, rendered only when the three counts sum above zero.
  - **Drill-down** — clicking a row toggles `expanded` and calls `loadRunFiles(key)`, which fetches the per-file list **once per run** and caches it in `filesByRun` component state (a run already cached or in flight is a no-op, so re-expanding costs nothing). `RunFileList` renders file **name** with a fallback to the file id in monospace, truncated with the full id in `title`, plus the per-file `StatusBadge` (now including a `NO_NEW_FILES` arm) and `error_detail`.
  - **Unchanged**: pagination (20/page), the Refresh button, the 30-second `setInterval` poll gated on `autoRefresh`, and the empty and error states.

  **Verified**: `tsc --noEmit` exit 0. **Not verified**: no Playwright run — `e2e/` contains no spec touching the history table (`autopilot-folder-browser.spec.ts` does not reference it), and no new E2E was written because proving this UI end-to-end needs the BE Gap 427 endpoints, which are being built in parallel and were not running.

* **FE Gap 434 — Sync History gained dismiss, clear-all and a retention setting** (paired with BE Gap 429, which supplies the DELETE endpoints and the config field). After Gap 428 the history read well but was append-only: a run could never be removed from view, the list only grew, and nothing told the user what was actually retained versus merely displayed.

  **Backend contract consumed** (BE Gap 429, coded against, not waited on):
  - `DELETE /api/autopilot/history/{batchId}` → 204/200; hides one run. `batchId` is a batch UUID or the literal `legacy`, same vocabulary as the `/files` route.
  - `DELETE /api/autopilot/history` → `{ hidden: number }`; hides every run.
  - `GET`/`PUT /api/autopilot/config` gains `history_retention_days: number` (7–365, default 90).
  - "Hidden" is display-only — hidden rows simply stop appearing in `GET /history` but remain in the database, so duplicate detection is unaffected. Retention is the only thing that hard-deletes, and only for skipped/failed/empty rows older than N days; imported rows are kept permanently for duplicate detection.

  **Proxy routes.**
  - `app/api/autopilot/history/route.ts` — added a `DELETE` handler alongside the existing `GET`, both `proxyJson(request, "/autopilot/history")`. `proxyJson` already forwards `request.method` verbatim and already handles a 204 null body (FE Gap 177), so no change to `lib/backendProxy.ts` was needed.
  - `app/api/autopilot/history/[batchId]/route.ts` — **new**, `DELETE` only, `proxyJson(request, "/autopilot/history/{batchId}")` with `encodeURIComponent` on the segment and `dynamic = "force-dynamic"`. Sits beside the Gap 428 `[batchId]/files/route.ts` and follows the same shape.

  **`AutopilotHistoryTable.tsx`.**
  - **Per-run dismiss** — `dismissRun(run)`: an `X` icon button at the right edge of each row, hidden until row hover/focus (`opacity-0 group-hover:opacity-100 focus:opacity-100`), swapped for a spinner while that run's request is in flight. It is **optimistic**: the row is filtered out of `data.items` and `total` decrements immediately, then `fetchHistory()` refills the page. On failure the pre-delete snapshot is restored, `actionError` is shown inline in the header strip, and a refetch reconciles with the server — the UI never claims a dismissal the backend rejected.
  - **Structural fix required by the dismiss button**: the run row was a single full-width `<button>` from Gap 428, and a `<button>` inside a `<button>` is invalid HTML. The row is now a flex `<div>` holding the expand toggle (`flex-1`) and the dismiss button as *siblings*, with the hover background moved to the wrapping `div`. `stopPropagation()` is still called in the dismiss handler as belt-and-braces.
  - **Clear history** — a `Trash2` header button, disabled when the list is empty or a clear is in flight, opens an **inline confirm strip** (not a modal) reading "Hide all N runs? Duplicate detection is unaffected." with Cancel / Hide all. `clearHistory()` is deliberately *not* optimistic: it awaits the DELETE, then resets `expanded`, the `filesByRun` cache and `page`, and refetches.
  - **Error surfacing** — `actionError` renders as its own strip under the header rather than replacing the whole component with the existing full-panel error state, so a failed dismiss never blanks the history the user is reading.
  - **Footnote** — a muted line above the pagination: "Hidden runs stay in duplicate detection. Skipped/failed entries older than {N} days are deleted automatically." `N` comes from a new optional `retentionDays?: number` prop, falling back to `DEFAULT_RETENTION_DAYS = 90` when the config has not loaded.

  **`app/ingestion/page.tsx`.** `autopilotConfig` gains `history_retention_days` (default `90`); `loadAutopilotConfig()` reads `res.data.history_retention_days ?? 90` and `saveAutopilotConfigPayload()` sends it, so it rides the existing Save Config / Sync Now path with no new request. A "History Retention (Days)" number input (`min={7} max={365}`) sits in the config form between Notification Emails and the approval-links toggle, with a one-line explanation of what is deleted versus kept, and the value is passed down as `<AutopilotHistoryTable retentionDays={…} />`.

  **Verified**: `node node_modules/typescript/bin/tsc --noEmit` exit 0 (`npx tsc` resolves to the wrong package in this checkout). **Not verified, and not claimed**: no Playwright run, no run against a live backend — the BE Gap 429 endpoints were being built in parallel and were not available; `e2e/` still contains no spec referencing the history table.
