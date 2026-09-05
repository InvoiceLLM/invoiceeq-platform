# Feature 3.1: Service Flow — Send Invoices Tab — **NOVA Agent**

**NOVA** (Smart Invoice Extraction) powers this tab. Extends [feature_3_ingestion.md](feature_3_ingestion.md). **Built 2026-07-29** — see Tasks below for exactly what shipped, including two deliberate deviations from this doc's original plan.

Adds the outbound counterpart to today's upload flow: a tab for uploading the tenant's own pre-made invoice PDFs for verification before send, visible only when the *Send Invoices* Settings toggle is on ([feature_16_settings.md](feature_16_settings.md) BE / [feature_10_settings.md](feature_10_settings.md) FE).

### File Coordinates (as built)
* Edited: `apps/invoice-fe/app/ingestion/page.tsx` — gains the tab header + outbound upload form + state, conditionally rendered.
* New component: `apps/invoice-fe/components/ingestion/SendInvoiceStatusTable.tsx` — new status set, not `StatusTable.tsx`'s.
* **Deviation from plan**: did *not* reuse `DropZone.tsx` — that component is built for multi-file batch drag-and-drop with tags, but the BE upload endpoint (`routers/outbound_invoices.py::upload_outbound_invoice`) deliberately takes exactly one file (`file: UploadFile`, not a list), matching this doc's own "upload-only, one invoice at a time" framing. A plain `<input type="file">` matches the actual endpoint contract; forcing `DropZone.tsx`'s multi-file UI onto a single-file backend would have been a mismatch, not a genuine reuse.
* New proxy routes: `apps/invoice-fe/app/api/outbound-invoices/upload/route.ts`, `apps/invoice-fe/app/api/outbound-invoices/[id]/confirm-send/route.ts` (named to match the BE router's actual path, `routers/outbound_invoices.py`'s `/outbound-invoices` prefix, rather than the originally-sketched `invoices-outbound` naming).
* **Deviation from plan**: no new status-polling proxy route was built. `SendInvoiceStatusTable.tsx` polls the existing `GET /api/invoices/[id]/route.ts` instead — that proxy is already flow-direction-agnostic (returns the full `Invoice` row, including `customer_name`/`flow_direction`, for any invoice ID) and reusing it avoids a redundant new endpoint doing the same lookup.
* Settings read: reuses the existing `GET /api/settings/service-flow` route (already built by Feature 10) directly via `fetch()` — no new settings proxy needed, since that endpoint already returns exactly `receive_invoices_enabled`/`send_invoices_enabled`.

### Functionality

**Tab visibility (matches the Dashboard/Auditor rule, not split-screen — Ingestion is an action screen):**
- Only *Receive* enabled: `page.tsx` renders exactly as it does today — no tab header at all.
- Only *Send* enabled: same single-view treatment, just showing the outbound uploader as the page's only content.
- Both enabled: a small tab header appears above the existing dropzone — *Receiving* / *Sending* — switching swaps the dropzone + status table underneath. Defaults to *Receiving*.

**Sending tab:** reuses `DropZone.tsx` unmodified, pointed at the new `/api/invoices-outbound/upload` proxy route instead of `/api/invoices/upload`. `SendInvoiceStatusTable.tsx` polls/streams the new status set (`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED/NEEDS_REVIEW → SENT → PAID/OVERDUE`) rather than `StatusTable.tsx`'s `COMPLETED`/`AUDIT_REQUIRED` set — different terminal states mean a new component rather than a fork-by-prop of the existing one.

**Deep-linking into the Sending tab (FE Gap 457, 2026-09-04).** `page.tsx` now reads `?tab=sending&builtInvoice=<id>&batch=<id>&name=<label>` through `useSearchParams()` and, once `sendVisible` is known, switches `activeTab` to `sending` and seeds a single `outboundInvoices` row from those ids. The Invoice Builder ([feature_20_invoice_builder.md](feature_20_invoice_builder.md)) is the first caller: a builder-created invoice is an ordinary outbound row, so the seeded entry renders through the same `SendInvoiceStatusTable` + `LogTerminal` pair an upload produces. The default export is now a `Suspense` wrapper (`IngestionPage`) around the page body (`IngestionPageContent`), which `useSearchParams()` requires in the app router. Nothing about the upload path changed.

**`NEEDS_REVIEW` rows** get a "Review" action linking into the outbound Auditor ([feature_4.1_vendor_flow_auditor.md](feature_4.1_vendor_flow_auditor.md)), mirroring how `AUDIT_REQUIRED` rows link today.

### Explicitly out of scope
- Any invoice creation/generation UI — that's [feature_17_invoice_builder.md](../../invoice-be/docs/feature_17_invoice_builder.md), deferred.
- Tag input / batch metadata tagging (`TagSelector.tsx`) — not carried over to the Sending tab in v1; outbound invoices are self-describing (customer name, invoice number already on the document).

### Connector-sourced files (Gap 98, added 2026-07-30)
Both tabs now also offer "Load from Google Drive" (~~/ Salesforce~~ — removed 2026-08-28, FE Gap 322) via `components/ingestion/ConnectorBrowseBar.tsx` — an icon per provider with an Active connection (set up once by an admin in `Settings → Connectors`, tenant-wide, not per-user), opening the existing `FolderTreeExplorer.tsx` in a modal. Receiving passes `direction="inbound"` (imported files feed the extraction pipeline like a normal upload); Sending passes `direction="outbound"` (files store for AR record-keeping, no extraction queued) — same `direction` semantics `trigger_file_import()`/`handle_import_connector_file()` already used for the manual-upload path. See `feature_7_connectors.md` for the connector-side detail.

### Tasks
- [x] **Task 3.1.1:** Added the *Receiving*/*Sending* tab header to `page.tsx`, gated on `GET /api/settings/service-flow`. Matches the doc's visibility rule exactly: Receive-only shows the page unchanged (no tab header), Send-only shows the outbound uploader as the sole content, both-enabled shows the tab switcher (defaults to Receiving).
- [x] **Task 3.1.2:** Built `SendInvoiceStatusTable.tsx` — single-invoice status card (not a multi-row ledger, since outbound upload is one file at a time), polls every 2s until a terminal status, shows customer name + total once extracted, and a "Confirm & Send" button on `VERIFIED`/`NEEDS_REVIEW`.
  - **Extended 2026-08-04 for Gap 84.** The outbound worker now durably persists `FAILED` to the invoice row instead of only broadcasting it over the ephemeral SSE channel (see `invoice-be/docs/feature_2_pipeline_extraction.md` → "Terminal-state convergence"), so this poll can see a real processing failure at all for the first time. Added `FAILED` to `OutboundStatus`, a red/`XCircle` badge matching `StatusTable.tsx`'s existing inbound Failed badge rather than a second visual language for the same outcome, and a red explanation block that shows the backend's `processing_failed`/`processing_timeout` alert message (falling back to generic re-upload guidance if there is none).
  - **Real bug found and fixed in the same pass**: the poll's stop condition read `status` out of the effect closure, and the effect only re-runs on `invoiceId` — so it was pinned to `"UPLOADED"` forever and the 2-second poll **never stopped**, even once the invoice reached `VERIFIED`/`SENT`. Now checked against the value each pass actually fetched. Fixed here rather than deferred because Gap 84's whole point is that a terminal state has to be recognised as terminal; adding `FAILED` to a stop list that never fired would have been cosmetic. Terminal set is now the named `TERMINAL_STATUSES` constant (`VERIFIED`, `NEEDS_REVIEW`, `SENT`, `FAILED`).
- [x] **Task 3.1.3:** Built the two proxy routes named above; reused the existing invoice-detail proxy for status polling instead of a third new route (see deviation note above).
- [x] **Task 3.1.4:** `NEEDS_REVIEW` rows show a "Open Outbound Auditor Console" link to `/invoices/outbound-review/{id}` — that page doesn't exist yet (it's `feature_4.1_vendor_flow_auditor.md`'s Task 4.1.2, not built as of this pass), so the link is wired ahead of its target, same forward-reference pattern used elsewhere in this doc set.

### Verification Plan
* **Automated**: `npx tsc --noEmit` clean across the whole FE app after these changes.
* **Manual Verification** (partially done): started a real dev server and confirmed `/ingestion` renders 200 with zero console errors with the new tab logic in place (Send disabled by default in this pass, so only the Receiving-only view was actually exercised — the tab-switching/Sending-view behavior itself has **not** been manually clicked through against a live backend). Full manual pass (both toggles on, real upload, real VERIFIED/NEEDS_REVIEW/SENT transition) still needs a live `docker compose` stack with a tenant that has `send_invoices_enabled=true`.
