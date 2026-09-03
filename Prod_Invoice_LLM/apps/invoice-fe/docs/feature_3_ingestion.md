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

---

### Document type on the ingestion surfaces — BE Feature 27 task G11 (2026-09-02, FE Gap 378)

Additive section (hard rule 4). Nothing above is rewritten. Design owner is
`apps/invoice-be/docs/feature_27_generic_extraction.md` §4's FE row; this section records
what was actually built here, including the one piece that could not be.

**Context, stated plainly because it governs every choice below.** BE Feature 27 makes
document type an explicit decision before extraction. Its persistence half — task **G9**,
`Invoice.doc_type` / `Invoice.doc_type_evidence` — **has not landed** (`models.py` carries
no such column as of 2026-09-02; the only `doc_type` in that file is `ChatAttachment`'s,
Feature 26). The flag `ENABLE_GENERIC_EXTRACTION` exists and defaults `False`. So **no API
response in this app returns `doc_type` today**, and Feature 27 requires the field stay
nullable/optional even after G9. Everything here is therefore written to the same rule:
*present → show it; absent → render byte-identical to what shipped before this change.*
The absent case is not a fallback, it is the only case that currently executes.

**`components/ingestion/StatusTable.tsx`**
* `StatusItem` gains `docType?: string | null`. Named camelCase, not `doc_type`, because
  `StatusItem` is this component's view model rather than a wire shape — the reconciliation
  fetch already maps `data.vendor_name` → `vendorName`. The wire key read is `doc_type`.
* `updateItemStatus()` gains a trailing `docType` parameter, threaded from `data.doc_type`
  on the mount reconciliation fetch (Gap 269's `GET /invoices/status/{id}`) and from
  `payload.doc_type` on the SSE branch.
* **It is merged, not overwritten**: `docType: docType ?? item.docType`. The other mapped
  fields (`vendorName`, `total`, `currency`) are assigned unconditionally, so an SSE tick —
  which carries only a status transition — blanks them. Copying that would make the badge
  appear on the reconciliation fetch and vanish on the next stream event. The existing
  fields' behaviour was deliberately left alone; it is pre-existing and out of this scope.
* `getDocTypeBadge()` renders a slate pill in the **File** cell, under the `PDF · size`
  line, with the same geometry as the status badges (`rounded-full`, `text-[10px]`,
  `bordered`, `colour/10` fill) and a deliberately quieter colour, because a document type
  is a fact about the file, not a pipeline outcome. `DELIVERY_NOTE` renders as
  "Delivery Note"; the raw enum value stays in the `title` attribute so a misclassification
  can be reported verbatim. `data-testid="doc-type-badge"`.
* **No new column was added, on purpose.** FE Gap 113 item 6 removed the old "Type" column
  precisely because it was the constant string "PDF" on every row. A fourth header that is
  empty on every row — which is every row today — would repeat that mistake. The table is
  still File / Stage / Status.

**`components/ingestion/DropZone.tsx` — the accept list is unchanged, and that is a
recorded blocker, not an oversight.** Feature 27 §4 widens `.pdf` to
`.pdf,.png,.jpg,.jpeg,.tiff` **only when the flag is on**, "surfaced via the existing
config/feature endpoint, not hardcoded". **There is no such endpoint.** Verified repo-wide
2026-09-02: every `ENABLE_*` in `invoice-be/config.py` is consumed server-side only
(`ENABLE_ASYNC_CHAT_QUEUE` is read inside `routers/chat.py`; this app adapts to the
*response shape*, never to a flag value), `main.py` registers no `/config` or `/features`
router, `routers/settings.py` exposes tenant configuration and credentials but no software
flags, and the only flag-shaped values this app sees are build-time `NEXT_PUBLIC_*` env
vars, which cannot reflect a backend process setting. Widening unconditionally would let a
user select a PNG the backend cannot extract with the flag off — `pdf_to_base64_images()`
returns `[]` for a non-PDF and the visual channel is lost silently. Inventing a `/features`
endpoint is backend scope. So: **both guards stay `.pdf`**, and they were refactored to
share one `ACCEPTED_EXTENSIONS` constant so the suffix check in `processFiles` and the
`accept` attribute on the input cannot drift apart when the flag exposure does arrive —
§4 is explicit that a mismatch means a dragged PNG gets past the picker and is rejected only
after selection. Behaviour is identical to before: PDF-only, same error string, same
`MAX_FILE_SIZE`.

**`app/invoices/review/[id]/page.tsx` (auditor console) — the evidence display.**
`InvoiceDetail` gains `doc_type?: string | null` and `doc_type_evidence?: string | null`
(snake_case here: this interface *is* the `GET /invoices/{id}` wire shape). Two rows were
added to the existing "Additional Extracted Metadata" panel — `Document Type` (raw enum
value, because this console is where a misclassification gets reported) and `Type Evidence`
(the verbatim printed phrase the classifier decided from, quoted). `doc_type` was added to
that panel's own visibility condition, so a record whose *only* extended metadata is a
document type still shows the panel; a record with none still shows nothing. The two rows
are independently conditional: Feature 27 E7's low-confidence path lands on `OTHER` with no
phrase to quote, so a type can legitimately exist without evidence. `data-testid`s
`doc-type-row` / `doc-type-evidence-row`.

**Not built, deliberately.** No documents-list page. Feature 27 E10 routes non-invoice
uploads to a separate `documents` table and G14's `GET /documents` endpoint does not exist
yet — building a page against an absent endpoint would be fiction. The outbound review
console (`app/invoices/outbound-review/[id]/page.tsx`) was not touched either: Feature 27
amendment A2 leaves the OUTBOUND direction on its existing schema in both flag states.

**Stale File Coordinate, corrected here rather than in §4.** Feature 27 §4 names
`apps/invoice-fe/types/invoice.ts` as the place to add `doc_type?: string`. **That file does
not exist.** `types/` contains only `chat.ts` (Feature 5). The ingestion status shape lives
as the exported `StatusItem` in `StatusTable.tsx` and the auditor shape as `InvoiceDetail`
in the review page — both were extended in place. No new `types/invoice.ts` was created:
inventing a shared types module for one optional field, when neither consumer imports from
the other, would be a refactor nobody asked for.

**Verification — real, and bounded.** `npx tsc --noEmit` exit 0. New Playwright spec
`e2e/feature27-doc-type.spec.ts`, **6 tests, all passing** against a real `next dev` server
with every `/api/**` call stubbed (the house pattern here — see
`e2e/gaps-282-284-286.spec.ts`): ledger renders with no badge and still exactly three column
headers when the status payload has no `doc_type` key at all; badge renders once, humanised,
with the raw value in `title`, when it does; the DropZone input's `accept` is still exactly
`.pdf` **and** a `.png` selection is still rejected by the suffix guard with the original
error string (both guards asserted, so a future one-sided widening fails loudly); the
auditor console shows neither row *and no panel* for a metadata-free record, shows both rows
plus the panel when type and evidence are present, and shows the type alone when evidence is
`null`. The four pre-existing failures in `e2e/audit-review-console.spec.ts` and
`e2e/gaps-282-284-286.spec.ts` were confirmed **pre-existing** by stashing these three file
changes and re-running: identical 4 failed / 11 passed at HEAD without them. **Not verified:**
nothing was run against a backend that actually returns `doc_type`, because none exists —
the present-case tests prove the rendering, not the wiring to a real payload, and that
end-to-end claim belongs to functional-tester after G9 lands.
