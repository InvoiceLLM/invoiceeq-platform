# Feature 3.1: Vendor Flow — Send Invoices Tab

Extends [feature_3_ingestion.md](feature_3_ingestion.md). Spec only — no implementation yet, pending approval of the full Vendor Flow document set.

Adds the outbound counterpart to today's upload flow: a tab for uploading the tenant's own pre-made invoice PDFs for verification before send, visible only when the *Send Invoices* Settings toggle is on ([feature_16_settings.md](feature_16_settings.md) BE / [feature_10_settings.md](feature_10_settings.md) FE).

### File Coordinates (planned)
* Edited (small, additive): `apps/invoice-fe/app/ingestion/page.tsx` — gains a tab header, conditionally rendered.
* New component: `apps/invoice-fe/components/ingestion/SendInvoiceStatusTable.tsx` — new status set, not `StatusTable.tsx`'s.
* Existing, imported-not-edited: `apps/invoice-fe/components/ingestion/DropZone.tsx` — reused as-is for the outbound dropzone; its drag/validate logic (reject non-PDF, >25MB, duplicate names) is direction-agnostic, so it's imported directly rather than forked.
* New proxy routes: `apps/invoice-fe/app/api/invoices-outbound/upload/route.ts`, `apps/invoice-fe/app/api/invoices-outbound/status/[jobId]/route.ts`.
* New settings read: `apps/invoice-fe/app/api/settings/vendor-flow/route.ts` — proxies `GET /settings/vendor-flow`, used by `page.tsx` to decide tab visibility.

### Functionality

**Tab visibility (matches the Dashboard/Auditor rule, not split-screen — Ingestion is an action screen):**
- Only *Receive* enabled: `page.tsx` renders exactly as it does today — no tab header at all.
- Only *Send* enabled: same single-view treatment, just showing the outbound uploader as the page's only content.
- Both enabled: a small tab header appears above the existing dropzone — *Receiving* / *Sending* — switching swaps the dropzone + status table underneath. Defaults to *Receiving*.

**Sending tab:** reuses `DropZone.tsx` unmodified, pointed at the new `/api/invoices-outbound/upload` proxy route instead of `/api/invoices/upload`. `SendInvoiceStatusTable.tsx` polls/streams the new status set (`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED/NEEDS_REVIEW → SENT → PAID/OVERDUE`) rather than `StatusTable.tsx`'s `COMPLETED`/`AUDIT_REQUIRED` set — different terminal states mean a new component rather than a fork-by-prop of the existing one.

**`NEEDS_REVIEW` rows** get a "Review" action linking into the outbound Auditor ([feature_4.1_vendor_flow_auditor.md](feature_4.1_vendor_flow_auditor.md)), mirroring how `AUDIT_REQUIRED` rows link today.

### Explicitly out of scope
- Any invoice creation/generation UI — that's [feature_17_invoice_builder.md](../../invoice-be/docs/feature_17_invoice_builder.md), deferred.
- Tag input / batch metadata tagging (`TagSelector.tsx`) — not carried over to the Sending tab in v1; outbound invoices are self-describing (customer name, invoice number already on the document).

### Tasks
- [ ] **Task 3.1.1:** Add the *Receiving*/*Sending* tab header to `page.tsx`, gated on `GET /settings/vendor-flow`.
- [ ] **Task 3.1.2:** Build `SendInvoiceStatusTable.tsx` for the new status set.
- [ ] **Task 3.1.3:** Build the two new proxy routes (upload, status poll/stream).
- [ ] **Task 3.1.4:** Wire `NEEDS_REVIEW` rows to the outbound Auditor deep-link.

### Verification Plan
* **Manual Verification:**
  - Receive-only tenant: confirm `/ingestion` is pixel-identical to today, no tab header.
  - Both enabled: confirm the tab switches correctly and each side's status table shows the right status set.
  - Upload a PDF on the Sending tab; confirm it reaches `VERIFIED` or `NEEDS_REVIEW` correctly and that the existing Receiving tab's uploads are entirely unaffected in the same session.
