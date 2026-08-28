# Feature 3: File Ingestion Portal & Active Tagging — **NOVA Agent**

**NOVA** (Smart Invoice Extraction) powers this screen. Develop the drag-and-drop file uploader, batch metadata tagger, and real-time processing queue status table.

**Product follow-on:** [Feature 13: Autopilot](feature_13_autopilot.md) upgrades this same `/ingestion` surface into an Autopilot decision brief (rename + recommendations + Ask). Feature 3 capabilities stay; Autopilot does not replace connectors (those stay in Settings / Feature 7).

### Theme & Styling Specifications
* Dashed drop zone: `border-2 border-dashed border-[#222D3D] hover:border-[#3B82F6] bg-opacity-30 rounded-xl`.
* Interactive tag chips: `bg-[#1E293B] border border-[#222D3D] rounded-full text-slate-300 hover:bg-[#334155] cursor-pointer`.

### File Coordinates
* Ingestion Page: [apps/invoice-fe/app/ingestion/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/ingestion/page.tsx) *(corrected 2026-07-13 — the real folder is `app/ingestion/`, not `app/ingest/`)*
* Tag Input: [apps/invoice-fe/components/ingestion/TagSelector.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/TagSelector.tsx)
* Drag-and-Drop Uploader: [apps/invoice-fe/components/ingestion/DropZone.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/DropZone.tsx) *(corrected — component is `DropZone.tsx`, not `FileUploader.tsx`)*
* Ingestion Status Table: [apps/invoice-fe/components/ingestion/StatusTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/StatusTable.tsx) *(corrected — component is `StatusTable.tsx`, not `QueueTable.tsx`)*
* Upload Proxy Route: [apps/invoice-fe/app/api/invoices/upload/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/invoices/upload/route.ts)
* Status Poll Proxy Route: [apps/invoice-fe/app/api/invoices/status/[jobId]/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/invoices/status/%5BjobId%5D/route.ts)
* Live Log Terminal (**added 2026-08-01, was missing from this list**): `apps/invoice-fe/components/ingestion/LogTerminal.tsx`
* Folder Watcher Proxy Route (**added 2026-08-01, was missing from this list**): `apps/invoice-fe/app/api/invoices/watcher/route.ts`
* Stream Proxy Route: [apps/invoice-fe/app/api/invoices/stream/[batchId]/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/invoices/stream/%5BbatchId%5D/route.ts)

### Functionality
`DropZone.tsx` handles both native drag events and a hidden file `<input>`, rejecting non-`.pdf` names, files over 25MB, and same-name duplicates client-side before calling `onChange`. `TagSelector.tsx` normalizes every tag to a leading `#` and dedupes on add. `StatusTable.tsx` decides polling vs. SSE by `jobIds.length >= 6`: below that it calls `pollJobStatus(jobId)` per file — a self-rescheduling `setTimeout(..., 2000)` loop hitting the status proxy route until a terminal status stops it; at 6+ it opens one `EventSource("/api/invoices/stream/{batchId}")` and routes each message by `payload.invoice_id`. Both paths update the same local `items: StatusItem[]` state, so the row UI (progress bar, badge, expandable `AUDIT_REQUIRED` alert panel) is identical regardless of which transport is active.

**Connector-sourced files (Gap 98, added 2026-07-30)**: below `DropZone.tsx`, `components/ingestion/ConnectorBrowseBar.tsx` shows a "Load from" icon row for any provider (Google Drive; ~~Salesforce~~ removed 2026-08-28, FE Gap 322) with an Active connection — set up once by an admin in `Settings → Connectors` (tenant-wide, not per-user; see `feature_7_connectors.md`), then usable by any user here. Renders nothing when no provider is Active, so it doesn't affect tenants without connectors configured. Opens the existing `FolderTreeExplorer.tsx` in a modal, passed `direction="inbound"` here (see `feature_3.1_vendor_flow_ingestion.md` for the Sending tab's `direction="outbound"` counterpart).

### Tasks
- [ ] **Task 3.1: Build Custom Metadata Tags Input**
  - Code an active tags panel. Add a text input allowing users to type tag text and hit `Enter` to create tag chips (e.g. `#Q1-2026`).
  - Provide close/delete `[x]` icons on each tag chip to remove it.
- [ ] **Task 3.2: Implement Drag-and-Drop File Loader**
  - Implement HTML5 drag-and-drop event captures or integration with `react-dropzone`.
  - Capture dropped file payloads and validate sizes (< 25MB). Display file names prior to submission.
- [ ] **Task 3.3: Code API Upload dispatcher**
  - Create the `POST` network dispatch method packing PDF files and the selected active tags list inside a `FormData` envelope sent to `apiClient.post("/invoices/upload")`, which routes through the Next.js proxy (see `feature_1_layout_theme.md` "API Call Path") to backend `POST /api/v1/invoices/upload`.
- [ ] **Task 3.4: Build Live Ingestion Queue Table**
  - Build a table showing columns: `File Name`, `Size`, `Type`, and `Status`.
  - **Status stream (revised 2026-08-11, Gap 207)**: originally hybrid (2s polling under 6 files, SSE at 6+) — the threshold bought nothing since `LogTerminal` already opened its own `EventSource` on the same stream endpoint regardless of batch size, so sub-6 batches just showed a visibly laggier ledger next to a live-scrolling log. Every batch size now uses the same `EventSource` connection; `pollJobStatus()`/the 2s poll loop no longer exists.
  - **Gap 227 — Live Processing Log showed duplicate/conflicting entries, closed 2026-08-18.** `LogTerminal.tsx` shares the same `EventSource` stream as `StatusTable.tsx` above, but the backend publishes two different kinds of message on it: real log lines (`queue_worker/handlers.py:570`, tagged `"type": "log_line"`) and status-transition events (`handlers.py:592,611,766,781,805`, which carry a `message` field but no `type` at all). `LogTerminal`'s old `onmessage` handler rendered anything with a `message` field, so both kinds interleaved in the same panel — the component's own docstring had specified filtering on `payload.type === "log_line"` all along, but the code never actually did it. Fixed by adding that filter. An earlier 2026-08-17 attempt (a "skip if it matches one of the last 3 rendered lines" dedup heuristic) was reverted the same day for not addressing this root cause — it suppressed some exact repeats without stopping status events from appearing at all.
  - Render progress bars for active uploads and display an inline expandable yellow card displaying validation warnings if status is `AUDIT_REQUIRED`.
- [x] **Task 3.5: Live Statistics Counters (Gap 14, 2026-07-27)**
  - Header counters (Found/Processed/Duplicates/Failed) in `StatusTable.tsx`, derived from the same `items` state driving the table rows.
  - Found and fixed a real bug along the way: `pollJobStatus()` (the 1-5 file path) had no branch for a `DUPLICATE` status — a duplicate upload silently stayed on "Processing" forever, polling never stopped, since none of the existing branches matched it. Added the missing branch, a `DUPLICATE` badge, and extended `StatusItem`'s status union.

### Layout fixes from Group A (2026-07-31) — Gaps 86 & 69

Both gaps were the same underlying complaint ("the page doesn't fit, I have to scroll to find things") with two separate causes, fixed together since they compound each other. (The planning doc this originally cited, `docs/guides/fe_gap_plan_group_a_layout_overflow.md`, was never committed — this section is the surviving writeup.)

* **Gap 86 — title and Receiving/Sending toggle were stacked on separate rows.** `PageHeader` already had an `actions` slot (added for the Dashboard's FilterBar merge, Gap 68) — Ingestion just never used it, rendering the toggle as its own sibling block below the title. Fixed by passing the toggle into `actions`; no new prop was needed. Still gated on `showTabs`, so a single-service tenant's view is unchanged (covered by its own regression test).
* **Gap 69 — left column overflowed the viewport, pushing Bulk Directory Scan off-screen.** Two changes: `space-y-6` → `space-y-4` on both the Receiving and Sending left columns, and the Bulk Directory Scan card became a collapsed-by-default disclosure (`aria-expanded`/`aria-controls`, chevron rotation). Bulk Directory Scan was chosen as the thing to fold because it's the least-used control in that column — a shared-drop-folder path, not the normal drag-and-drop route — and its header row stays visible, so it's more discoverable collapsed than it was below the fold.

**Measured at 1280×720, before → after** (captured via a throwaway Playwright measurement harness, since "it overflows" needed a number rather than an impression):

| Metric | Before | After |
|---|---|---|
| Shell `<main>` overflow | 178 px | 1 px (sub-pixel) |
| Left column height | 718 px | 541 px |
| Bulk Directory Scan bottom edge vs. fold | 146 px **below** | 31 px **above** |

Regression coverage: `e2e/group-a-layout-overflow.spec.ts` — geometry assertions (`boundingBox()` vs. viewport), not visibility assertions, because an element pushed below the fold still counts as "visible" to Playwright's default definition, which is exactly why this shipped unnoticed. Confirmed failing against the pre-fix code before being confirmed passing against the fix.

### Fixes — 2026-08-11 (Gaps 204, 207, 181)

* **Gap 204 — in-flight ingestion state discarded on navigation.** `batchId`/`jobIds`/`trackedFiles` were plain `useState`, so leaving `/ingestion` mid-batch and returning showed an empty ledger even though the worker was still processing (`StatusTable`/`LogTerminal` are both keyed off `batchId`). Fixed with the same module-level-cache pattern Gap 146 already uses for unsubmitted files (`cachedFiles`/`cachedTags`/`cachedOutboundFiles`, declared at the top of `app/ingestion/page.tsx` — note: **not** `lib/ingestionDraft.ts`, which exists but turned out to be unused/orphaned when this doc previously implied it was the mechanism). Added `cachedBatchId`/`cachedJobIds`/`cachedTrackedFiles` alongside it, same `useState(() => cachedX)` + sync-`useEffect` shape. Survives client-side nav only, not a full reload — same accepted limitation as Gap 146.
* **Gap 207 — sub-6-file batches lagged on 2s polling instead of streaming.** See Task 3.4 above for the core fix (removed the `jobIds.length >= 6` gate and the dead polling code path). While merging the paths, also fixed a latent bug the merge would otherwise have turned into a regression: the SSE handler's progress math only recognized `"COMPLETED"` as 100%, defaulting every other status (including terminal ones like `AUDIT_REQUIRED`/`DUPLICATE`/`FAILED`) to a stuck 60% — invisible while only 6+-file batches used SSE, but would have shown every small batch's progress bar frozen at 60% once SSE became universal. Added a `TERMINAL_STATUSES` list so all terminal statuses reach 100%, matching what the removed polling code used to do.
* **Gap 181 — Bulk Directory Scan reported showing a "system error."** Ruled out one hypothesis (no `showDirectoryPicker()`/File System Access API anywhere in this codebase) and hardened the client-side folder picker's `onChange` (previously no error handling at all). Neither turned out to be the actual report: **live user testing confirmed the real issue is the "OR SERVER PATH" input**, not the folder picker (which works fine) — submitting a server path returns `"Directory watcher isn't enabled for this environment"` because `WATCHER_ALLOWED_BASE_DIR` was never in `apps/invoice-be/.env.example`. This is the backend's intentional path-traversal guard doing exactly what it's tested to do when unset, not an application bug. Fixed at the source: added the setting to `.env.example` with a git-tracked `watched_invoices/` folder to point it at (full writeup: `apps/invoice-be/docs/be_features_tracker.md` Gap 12). Closed.

### Verification Plan
* **Manual Verification**: Drop multiple PDFs, check that tags are sent, and confirm the progress bars update based on SSE socket triggers.
