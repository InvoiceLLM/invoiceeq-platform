# Feature 4: Split-Screen Auditor Review Console

Develop the read-only verification console, visual PDF coordinate viewer, and alert override dismiss handlers.

### Theme & Styling Specifications
* Bounding Box Overlays: `border border-[#10B981] bg-[#10B981] bg-opacity-10 shadow-[0_0_10px_rgba(16,185,129,0.4)]`.
* Alert Banner Cards: `bg-yellow-950/20 border border-yellow-700/50 text-yellow-200 rounded-lg`.
* Verified Details Box: Inputs must be styled as read-only fields (`bg-[#1E293B] border-[#222D3D] text-slate-300 pointer-events-none`) until edited.
* Editable Field (active correction): `border-[#3B82F6] bg-[#1E293B] text-slate-100` — replaces the read-only style once an auditor clicks into a field (Task 4.6).

### File Coordinates
* Auditor Page: [apps/invoice-fe/app/invoices/review/[id]/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/invoices/review/[id]/page.tsx)
* PDF Canvas Viewer: [apps/invoice-fe/components/audit/PdfViewerCanvas.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/audit/PdfViewerCanvas.tsx)
* Alert Console: [apps/invoice-fe/components/audit/AlertConsole.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/audit/AlertConsole.tsx)
* Proxy Routes: [apps/invoice-fe/app/api/invoices/[id]/pdf/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/invoices/%5Bid%5D/pdf/route.ts), [apps/invoice-fe/app/api/audit/resolve/[id]/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/audit/resolve/%5Bid%5D/route.ts)

- [x] **Task 4.1: Render Document PDF Canvas**
  - Implemented via `<iframe>` pointing to `GET /api/v1/invoices/{id}/pdf` with Zoom + Rotate toolbar in `PdfViewerCanvas.tsx`.
- [x] **Task 4.2: Draw Coordinate Bounding Boxes**
  - Absolute-positioned `<div>` overlays with emerald green border + glow shadow rendered from the `coordinates: {x, y, width, height, label}[]` prop on `invoice.coordinates[]` in `PdfViewerCanvas.tsx`.
- [x] **Task 4.3: Implement Read-Only Metadata Inspector**
  - `ReadOnlyField` components display: `Vendor Name`, `Invoice Date`, `Total Amount`, `Tax Amount`, `Due Date`, `PO Number`. All fields are `pointer-events-none` + `readOnly`.
  - *Note*: superseded by Task 4.6 below — fields become editable to capture auditor corrections.
- [x] **Task 4.4: Code Active Alerts Review & Dismissal Actions**
  - `AlertConsole.tsx` renders per-alert yellow warning cards each with a `Dismiss` button calling `PUT /api/v1/audit/resolve/{id}`.
  - `Mark Paid & Finalize` and `Reject Invoice` buttons in the review page call `PUT /audit/resolve` with `status: PAID/REJECTED` and dismiss all remaining alerts.
- [x] **Task 4.5: Confidence-based field highlighting**
  - Extend `ExtractedDataForm`/the metadata inspector to visually flag low-confidence fields (e.g. amber border/badge) using the backend's per-field confidence scores, so auditors can scan straight to what needs review instead of re-checking every field.
- [x] **Task 4.6: Editable Metadata Inspector & Correction Capture**
  - Convert each `ReadOnlyField` into an editable input on click (drop `pointer-events-none` + `readOnly`; apply the Editable Field style above while dirty).
  - Track a `corrections: Record<string, any>` diff of fields changed from their original extracted values.
  - Include `corrections` in the `PUT /api/v1/audit/resolve/{id}` payload sent by Dismiss / `Mark Paid & Finalize` / `Reject Invoice`, per `docs/feature_7_audit.md` Task 7.3.
- [x] **Task 4.8: Line Items Table (Gap 10, 2026-07-27)**
  - The line items section only ever rendered Description + Total in a plain list — `quantity`/`unit_price` were already present on the `LineItem` type and returned by the backend, just never rendered. Converted to a real table: Description, Qty, Unit Price, Total, plus a subtotal footer row.
- [x] **Task 4.7: Rule Suggestion Prompt**
  - When the `PUT /audit/resolve` response includes a `suggested_rule: {scope, field, sample_correction}` object (per `docs/feature_7_audit.md` Task 7.4), surface an inline "Want to save this as a rule?" banner.
  - Accepting it opens a Trainer sandbox session pre-seeded with the suggested scope (Global or Vendor) and the sample correction already in chat context — see `feature_6_trainer.md` Task 6.8 / `docs/feature_10_trainer.md` Task 10.11 — instead of a blank session.

### Recent Fixes
* **P0 Bug - AlertConsole 400 Error**: Fixed Jul 25, 2026. The `status` field was previously required on every resolve call, causing `AlertConsole.tsx`'s "Dismiss" button (which sent `status: currentStatus`, e.g., `"AUDIT_REQUIRED"`) to always fail with a 400 error since the backend only accepted `PAID`/`REJECTED`. Made `status` optional on the backend so omitting it correctly dismisses/corrects without finalizing the invoice.
* **Gap 26: "Report an issue" only reachable from `AUDIT_REQUIRED` invoices** — Fixed Jul 27, 2026, two parts:
  1. **The review page was unreachable from anywhere in the app.** This doc always correctly pointed at `app/invoices/review/[id]/page.tsx`, but every actual link to it elsewhere in the app — `Sidebar.tsx`'s "Invoices" nav item, `RecentInvoicesTable.tsx`'s row-action menu, `StatusTable.tsx`'s "Open Auditor Console" link, `CitationPill.tsx`'s citation click-through — pointed at `/audit` or `/audit?id=...`, a route that has never existed (no `app/audit/page.tsx`, no rewrite, no middleware). Fixed all four to point at `/invoices/review/{id}` (`CitationPill.tsx` also passes through `?page=`, currently unread by the review page but harmless); removed the Sidebar's "Invoices" item and `RecentInvoicesTable`'s "View all ledger" link rather than repointing them at `/dashboard`, since there's no dedicated invoices-queue list page to send a bare (no-id) link to and two nav items for the same route would both show active at once. A proper Invoices Queue page is a real, separate gap — not scoped here.
  2. **No way to save a correction without forcing a status change.** On a `COMPLETED`, never-flagged invoice, `sa_alerts` is empty, so `AlertConsole` shows only a static "No active discrepancy warnings" message with no button — the only way to submit `corrections` was via `Mark Paid & Finalize`/`Reject Invoice`, both of which force a status transition. Added a "Save Correction" button (shown whenever there are unsaved corrections and the invoice isn't already resolved) that calls the existing `handleResolve()` with no target status — backend: `docs/feature_7_audit.md` Gap 53.

### Verification Plan
* **Manual Verification**: Launch the review screen for a flagged invoice. Confirm metadata fields switch to editable on click, that a corrected value is included in the `PUT /audit/resolve` payload, and that clicking "Dismiss" updates the alert list and clears overlays.
* **Gap 26 verification**: confirmed live — `/audit?id=X` 404s, `/invoices/review/{real-id}` returns 200 and the correct page chunk loads; Dashboard's Sidebar/actions and Ingestion's StatusTable no longer reference `/audit` anywhere (checked via the rendered HTML). A correction-only `PUT /audit/resolve` call against a real `COMPLETED` invoice in the running dev DB persisted the value and left status untouched.
