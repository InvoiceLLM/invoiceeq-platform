# Feature 4.1: Service Flow — Outbound Auditor Tab — **SENTINEL Agent**

**SENTINEL** (Invoice Risk Detection) powers this tab. Extends [feature_4_auditor.md](feature_4_auditor.md). **Built 2026-07-29** — see Tasks below for exactly what shipped, including one scope note on the overdue-banner text.

Adds the pre-send validation console for outbound invoices, plus the "apply as standing rule" checkbox from [feature_7.1_vendor_flow_auditor.md](../../invoice-be/docs/feature_7.1_vendor_flow_auditor.md).

### File Coordinates (planned)
* New page: `apps/invoice-fe/app/invoices/outbound-review/[id]/page.tsx` — separate route, not a param on the existing review page, since the resolve target/status set differ.
* New component: `apps/invoice-fe/components/audit/OutboundAlertConsole.tsx` — not a fork of `AlertConsole.tsx`'s file, but the same visual language (Theme & Styling Specifications below carry over unchanged).
* Existing, imported-not-edited: `apps/invoice-fe/components/audit/PdfViewerCanvas.tsx` — reused as-is; rendering a PDF and its bounding boxes is direction-agnostic.
* New proxy route: `apps/invoice-fe/app/api/outbound-audit/resolve/[id]/route.ts` → `PUT /outbound-audit/resolve/{id}`.
* New component: `apps/invoice-fe/components/audit/OutboundInvoicesTable.tsx` — the outbound tab/half of the new unified Invoices/Audit queue screen built in `feature_4_auditor.md` Task 4.9. Mirrors that screen's server-pagination pattern (8 rows/page, `limit`/`offset`/`X-Total-Count`), reading `GET /outbound-dashboard/invoices` (see `feature_8.1_vendor_flow_dashboard.md`, BE) instead of `GET /invoices`. Status tabs use outbound's real lifecycle (`Verified`/`Needs Review`/`Sent`/`Paid`/`Overdue`), not inbound's.
* New component: `apps/invoice-fe/components/audit/OutboundFilterBar.tsx` — customer-name dropdown (mirrors inbound's vendor dropdown, built from distinct `customer_name` values) + date range. No tag filter — outbound invoices don't carry `tags`.
* Not on Dashboard: **correction (2026-07-29)** — an earlier pass of `feature_2.1_vendor_flow_dashboard.md` placed this table on Dashboard, split-screen with the metrics grid. Moved here instead, per the Dashboard/Audit split decision (Dashboard is overview-only; the queue lives here, alongside inbound's own tab).

### Functionality

**Tab visibility:** same rule as Ingestion — a small *Receiving*/*Sending* tab header, only shown when both Settings toggles are on; otherwise a single undivided view (today's Auditor if only Receive is on, or just the outbound console if only Send is on).

**`OutboundAlertConsole.tsx`:** renders the same alert-card visual style as `AlertConsole.tsx` (yellow alert banners) for the alert types `feature_7.1` produces (`missing_required_field`, math/faithfulness mismatches, `duplicate_invoice_number`). **Scope note**: the `due_date`-past-today follow-up banner originally planned *inside this component* is instead surfaced on the `/invoices` page's outbound tab (`OutboundInvoicesTable.tsx`'s "Overdue" badge/tab) — `SENT`/`PAID` invoices don't route through `OutboundAlertConsole` at all in the built review page (they show the Mark Paid action instead of a correction console), so there's no natural place inside this specific component for that banner to live.

**Standing-rule checkbox:** below the correction diff, one checkbox — *"Apply this as a standing rule for all future outbound invoices?"* — sends an extra `apply_as_standing_rule: true` flag in the `PUT /outbound-audit/resolve/{id}` payload. No sandbox, no Trainer deep-link — this is deliberately simpler than the inbound "suggested_rule" banner (Task 4.7), since there's no vendor-scoped rule to review before committing (see `feature_7.1` for the reasoning).

**`PdfViewerCanvas.tsx` reuse:** imported directly for the outbound document preview + coordinate overlay, pointed at a new PDF proxy route for the outbound invoice — zero changes to the component itself.

### Explicitly out of scope
- Any "want to save this as a rule?" banner styled after Task 4.7 — replaced entirely by the simpler standing-rule checkbox above.
- Line Items Table (FE Gap 10, still open on the inbound side) — not duplicated here; can be added to both consoles together later if built.

### Tasks
- [x] **Task 4.1.1:** Built `OutboundAlertConsole.tsx` — alert rendering, editable corrections (shared `EditableField`-style click-to-edit inline in the review page, not a separate component), standing-rule checkbox.
- [x] **Task 4.1.2:** Built `app/invoices/outbound-review/[id]/page.tsx`, reusing `PdfViewerCanvas.tsx` unmodified. Buttons: **Approve & Send** (`VERIFIED`/`NEEDS_REVIEW`) and **Mark Paid** (`SENT`) — no Reject, per the design reasoning already in `feature_2.1_vendor_flow_ingestion.md`.
- [x] **Task 4.1.3:** Built the resolve proxy route (`app/api/outbound-audit/resolve/[id]/route.ts`).
- [x] **Task 4.1.4:** Added the *Receiving*/*Sending* tab header directly on `/invoices` (not shared with Ingestion's tab as one component — each page implements its own small tab state, matching how the original Ingestion tab was built too; decided not worth extracting for two call sites).
- [x] **Task 4.1.5:** Built `OutboundInvoicesTable.tsx` + `OutboundFilterBar.tsx` as the outbound tab of `/invoices`, reading `GET /outbound-dashboard/invoices`. 4-tab shape decided during build: **All / Pending / Paid / Overdue** — Pending bundles every in-flight status (`UPLOADED`→`SENT`), mirroring inbound's "Pending" bundling logic exactly, rather than exposing all 5 raw lifecycle states as separate tabs.

### Verification Plan
* **Automated**: `npx tsc --noEmit` clean across the whole FE app.
* **Manual Verification** (partially done): real dev server confirmed `/invoices` (both tabs), `/invoices/outbound-review/[id]`, and `/ingestion` all render 200 with zero console errors after these changes (one unrelated stale `.next` build-cache issue was hit and resolved by clearing the cache — not a code defect). **Not yet done**: an actual click-through — correcting a real field, checking the standing-rule box, confirming the *next* uploaded invoice reflects it — needs a live backend with a tenant that has `send_invoices_enabled=true` and at least one `NEEDS_REVIEW` outbound invoice, which this pass didn't have. Confirmed via `tsc`/grep that `/invoices/review/[id]` and `AlertConsole.tsx` (inbound) have zero changes from this work.
