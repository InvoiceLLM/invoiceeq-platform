# Feature 4: Split-Screen Auditor Review Console — **SENTINEL Agent**

**SENTINEL** (Invoice Risk Detection) powers this screen. Develop the read-only verification console, visual PDF coordinate viewer, and alert override dismiss handlers.

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
  - `Approve Invoice` and `Reject Invoice` buttons in the review page call `PUT /audit/resolve` with `status: PAID/REJECTED` and dismiss all remaining alerts. *(FE Gap 218, Aug 12, 2026: inbound primary action label renamed from "Mark Paid & Finalize" to "Approve Invoice"; internal `PAID` status unchanged. Outbound review console unchanged.)*
- [x] **Task 4.10 / Gap 125: Staff notify multi-select**
  - Before Mark Paid / Reject, auditor multi-selects from the tenant’s **inbound** authorized email set; payload includes `notify_emails[]` (must ⊆ set). App never emails customers — only registered staff addresses.
- [x] **Task 4.5: Confidence-based field highlighting**
  - Extend `ExtractedDataForm`/the metadata inspector to visually flag low-confidence fields (e.g. amber border/badge) using the backend's per-field confidence scores, so auditors can scan straight to what needs review instead of re-checking every field.
- [x] **Task 4.6: Editable Metadata Inspector & Correction Capture**
  - Convert each `ReadOnlyField` into an editable input on click (drop `pointer-events-none` + `readOnly`; apply the Editable Field style above while dirty).
  - Track a `corrections: Record<string, any>` diff of fields changed from their original extracted values.
  - Include `corrections` in the `PUT /api/v1/audit/resolve/{id}` payload sent by Dismiss / `Approve Invoice` / `Reject Invoice`, per `docs/feature_7_audit.md` Task 7.3.
- [x] **Task 4.8: Line Items Table (Gap 10, 2026-07-27)**
  - The line items section only ever rendered Description + Total in a plain list — `quantity`/`unit_price` were already present on the `LineItem` type and returned by the backend, just never rendered. Converted to a real table: Description, Qty, Unit Price, Total, plus a subtotal footer row.
- [x] **Task 4.7: Rule Suggestion Prompt**
  - When the `PUT /audit/resolve` response includes a `suggested_rule: {scope, field, sample_correction}` object (per `docs/feature_7_audit.md` Task 7.4), surface an inline "Want to save this as a rule?" banner.
  - Accepting it opens a Trainer sandbox session pre-seeded with the suggested scope (Global or Vendor) and the sample correction already in chat context — see `feature_6_trainer.md` Task 6.8 / `docs/feature_10_trainer.md` Task 10.11 — instead of a blank session.

### Recent Fixes
* **Gap 141 (Audit Queue side) / Gap 201: fake fallback dropdown data and a timezone date-shift bug on this page** — Fixed Aug 11, 2026. Two independent fixes to `app/invoices/page.tsx`: (1) removed its `DEFAULT_VENDORS`/`DEFAULT_TAGS` fallback (Gap 141) — `uniqueVendors`/`uniqueTags` now derive from real invoice data only, since selecting one of the five fictional vendor names returned zero rows against `routers/invoices.py`'s exact-match filter; (2) `getDatesForRange()`'s date-range math converted through UTC before formatting (`toISOString().split("T")[0]`), shifting every date-range filter by a day for any non-UTC user (Gap 201) — replaced with `lib/utils.ts::toLocalDateString()` (new shared helper), which reads the `Date`'s own local year/month/day. Same UTC-conversion bug existed identically in `feature_2_dashboard.md`'s `dashboard/page.tsx` and was fixed there too. **Not fixed here**: `be_features_tracker.md` Gap 191 (backend filters on the wrong date column and drops NULL-dated invoices) — the FE fix removes the off-by-one-day but date filtering isn't fully correct until that's also addressed.
* **Gap 200: Rejected invoices showed as "Processing"; status dropdown was a no-op off the "All" tab** — Fixed Aug 11, 2026. `RecentInvoicesTable.tsx`'s `getStatusBadge()` had no `REJECTED` case (fell through to the `PROCESSING` default, a blue spinner) even though the backend (`routers/audit.py`) writes `REJECTED` correctly — added a `REJECTED` case (rose/`XCircle`, matching `FAILED`). Separately, `FilterBar.tsx`'s status `<select>` stayed enabled on every tab even though `app/invoices/page.tsx` only reads its value on the "All" tab (a tab's own status silently wins otherwise) — added a `statusFilterDisabled` prop, set by the page to `activeTab !== "all"`, so the dropdown visually disables (with a tooltip) instead of looking live while doing nothing. `FilterBar.tsx`'s `STATUSES` list was also missing `REJECTED`/`DUPLICATE` entirely (see `feature_2_dashboard.md` for that component's own doc entry).
* **P0 Bug - AlertConsole 400 Error**: Fixed Jul 25, 2026. The `status` field was previously required on every resolve call, causing `AlertConsole.tsx`'s "Dismiss" button (which sent `status: currentStatus`, e.g., `"AUDIT_REQUIRED"`) to always fail with a 400 error since the backend only accepted `PAID`/`REJECTED`. Made `status` optional on the backend so omitting it correctly dismisses/corrects without finalizing the invoice.
* **Gap 218 (FE, Aug 12, 2026) — inbound approve button label**: `app/invoices/review/[id]/page.tsx` primary finalize action now reads **Approve Invoice** (AP semantics: authorize payment, not record it). Outbound `outbound-review/[id]/page.tsx` **Mark Paid** unchanged. `e2e/audit-review-console.spec.ts` updated.
* **Gap 277 (FE, Aug 20, 2026) — Record INBOUND invoice as Paid directly from the Audit Queue table**: `components/dashboard/RecentInvoicesTable.tsx` added "Mark as Paid" action to the row dropdown menu for active inbound invoices, calling `PUT /api/audit/resolve/{id}` with `status: "PAID"`, prompting user confirmation and triggering `onStatusChange` refresh in `app/invoices/page.tsx`.

* **Gap 26: "Report an issue" only reachable from `AUDIT_REQUIRED` invoices** — Fixed Jul 27, 2026, two parts:
  1. **The review page was unreachable from anywhere in the app.** This doc always correctly pointed at `app/invoices/review/[id]/page.tsx`, but every actual link to it elsewhere in the app — `Sidebar.tsx`'s "Invoices" nav item, `RecentInvoicesTable.tsx`'s row-action menu, `StatusTable.tsx`'s "Open Auditor Console" link, `CitationPill.tsx`'s citation click-through — pointed at `/audit` or `/audit?id=...`, a route that has never existed (no `app/audit/page.tsx`, no rewrite, no middleware). Fixed all four to point at `/invoices/review/{id}` (`CitationPill.tsx` also passes through `?page=`, currently unread by the review page but harmless); removed the Sidebar's "Invoices" item and `RecentInvoicesTable`'s "View all ledger" link rather than repointing them at `/dashboard`, since there's no dedicated invoices-queue list page to send a bare (no-id) link to and two nav items for the same route would both show active at once. A proper Invoices Queue page is a real, separate gap — not scoped here.
  2. **No way to save a correction without forcing a status change.** On a `COMPLETED`, never-flagged invoice, `sa_alerts` is empty, so `AlertConsole` shows only a static "No active discrepancy warnings" message with no button — the only way to submit `corrections` was via `Mark Paid & Finalize`/`Reject Invoice`, both of which force a status transition. Added a "Save Correction" button (shown whenever there are unsaved corrections and the invoice isn't already resolved) that calls the existing `handleResolve()` with no target status — backend: `docs/feature_7_audit.md` Gap 53.

### Dashboard/Audit split — new Invoices/Audit queue screen (2026-07-29, addresses Gap 28)

Dashboard's embedded `RecentInvoicesTable`/`FilterBar` (today's only invoice-listing surface — see `feature_2_dashboard.md`) is moving here, becoming the entry point in front of this doc's existing per-invoice review console. Reason: Dashboard's job is an at-a-glance overview; browsing/filtering/paging the full invoice queue is a separate, action-oriented workflow that deserves its own screen — especially once the outbound side (`feature_4.1_vendor_flow_auditor.md`) adds a second table that would otherwise have to squeeze onto Dashboard alongside it.

**File Coordinates (planned, additive):**
* New page: `apps/invoice-fe/app/invoices/page.tsx` — new route, the unified queue screen.
* Relocated, not rewritten: `apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx` + `FilterBar.tsx` — same components, same server-pagination contract (8 rows/page, `limit`/`offset`/`X-Total-Count`, All/Paid/Pending/Rejected tabs), just imported into the new page instead of `dashboard/page.tsx`. No behavior change to the components themselves.
* Edited: `apps/invoice-fe/components/layout/Sidebar.tsx` — re-add an **"Invoices"** nav item pointing at `/invoices` (the item removed during Gap 26 pointed at the dead `/audit` route and had nowhere real to go; now it does).
* Each row's existing "Auditor Review Console" action continues to link to `/invoices/review/{id}` — unchanged.
* If Service Flow (outbound) has shipped by the time this is built: the same page also hosts `OutboundInvoicesTable.tsx`/`OutboundFilterBar.tsx` (`feature_4.1_vendor_flow_auditor.md`) as a second tab/toggle (Receiving/Sending) — not side-by-side, since this screen's job is depth per direction, not glance-ability across both at once (that's what Dashboard's `NeedsAttentionWidget` is for).

### Tasks
- [x] **Task 4.10 (Gap 67 / BE Gap 62): "Apply as standing rule" checkbox on the correction UI — done 2026-07-29.**
  - Checkbox added to `app/invoices/review/[id]/page.tsx`, shown alongside the existing corrections banner (only when the invoice has a resolved `vendor_name` — standing rules are vendor-scoped, nothing to attach to otherwise). Passed through to both call sites: the page's own `handleResolve()` (Mark Paid/Reject/Save Correction) and `AlertConsole.tsx`'s Dismiss action (new `applyAsStandingRule` prop), as `apply_as_standing_rule` in the `PUT /audit/resolve/{id}` payload — one shared checkbox state, not duplicated per button.
  - Result banner (green "Standing rule applied" + the rule text, or amber with the backend's rejection reason) renders after any of those calls return a `standing_rule_result`; checkbox resets after each save regardless of outcome.
  - Backend piece: `feature_7_audit.md` Task 7.5.
  - Verified: `npx tsc --noEmit` clean; dev server confirmed `/invoices/review/[id]` still renders 200 with no console errors after the change.
- [x] **Task 4.9 (Gap 28): Build the unified Invoices/Audit queue screen — done 2026-07-29.**
  - Built `app/invoices/page.tsx` — imports `RecentInvoicesTable.tsx` + `FilterBar.tsx` unchanged (same pagination/filter/tab props, same components, not forked), with its own copy of the fetch/pagination state (the state itself doesn't move as a file, since it lived inside `dashboard/page.tsx`'s component body — only the *usage* relocates).
  - Re-added Sidebar's "Invoices" nav item (`ListChecks` icon), pointed at `/invoices`.
  - **Redundant-code removal done**: `dashboard/page.tsx` no longer has any invoice-pagination state/fetch logic or `RecentInvoicesTable` import — see `feature_2_dashboard.md` Task 2.7.

### Verification Plan
* **Manual Verification**: Launch the review screen for a flagged invoice. Confirm metadata fields switch to editable on click, that a corrected value is included in the `PUT /audit/resolve` payload, and that clicking "Dismiss" updates the alert list and clears overlays.
* **Gap 26 verification**: confirmed live — `/audit?id=X` 404s, `/invoices/review/{real-id}` returns 200 and the correct page chunk loads; Dashboard's Sidebar/actions and Ingestion's StatusTable no longer reference `/audit` anywhere (checked via the rendered HTML). A correction-only `PUT /audit/resolve` call against a real `COMPLETED` invoice in the running dev DB persisted the value and left status untouched.
* **Task 4.9 verification**: `npx tsc --noEmit` clean across the whole FE app; started the real dev server and confirmed both `/dashboard` (200, "Command Center" + "Needs Attention" widget render) and `/invoices` (200, page renders) with zero console errors/warnings in the server log; confirmed via grep that no other file still imports `RecentInvoicesTable` outside these two pages, and Sidebar's new "Invoices" link renders. **Not yet verified**: full pagination/filter behavior against real backend data (no live BE/DB in this pass) — recommend a follow-up manual pass once a dev environment with seeded invoices is available, to confirm Next/Previous and tab filtering behave identically to their old Dashboard location.
