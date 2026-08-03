# Feature 3: File Ingestion Portal & Active Tagging — **NOVA Agent**

**NOVA** (Smart Invoice Extraction) powers this screen. Develop the drag-and-drop file uploader, batch metadata tagger, and real-time processing queue status table.

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

**Connector-sourced files (Gap 98, added 2026-07-30)**: below `DropZone.tsx`, `components/ingestion/ConnectorBrowseBar.tsx` shows a "Load from" icon row for any provider (Google Drive/Salesforce) with an Active connection — set up once by an admin in `Settings → Connectors` (tenant-wide, not per-user; see `feature_7_connectors.md`), then usable by any user here. Renders nothing when no provider is Active, so it doesn't affect tenants without connectors configured. Opens the existing `FolderTreeExplorer.tsx` in a modal, passed `direction="inbound"` here (see `feature_3.1_vendor_flow_ingestion.md` for the Sending tab's `direction="outbound"` counterpart).

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
  - Implement the hybrid client-side status stream:
    - **Polling (1-5 files)**: Runs queries fetching status updates every 2 seconds via the status proxy route.
    - **SSE Connection (6+ files)**: Establishes a browser `EventSource` connection against the stream proxy route.
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

### Verification Plan
* **Manual Verification**: Drop multiple PDFs, check that tags are sent, and confirm the progress bars update based on SSE socket triggers.
