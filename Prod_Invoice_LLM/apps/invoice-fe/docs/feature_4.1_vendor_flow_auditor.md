# Feature 4.1: Service Flow — Outbound Auditor Tab

Extends [feature_4_auditor.md](feature_4_auditor.md). Spec only — no implementation yet, pending approval of the full Service Flow document set.

Adds the pre-send validation console for outbound invoices, plus the "apply as standing rule" checkbox from [feature_7.1_vendor_flow_auditor.md](../../invoice-be/docs/feature_7.1_vendor_flow_auditor.md).

### File Coordinates (planned)
* New page: `apps/invoice-fe/app/invoices/outbound-review/[id]/page.tsx` — separate route, not a param on the existing review page, since the resolve target/status set differ.
* New component: `apps/invoice-fe/components/audit/OutboundAlertConsole.tsx` — not a fork of `AlertConsole.tsx`'s file, but the same visual language (Theme & Styling Specifications below carry over unchanged).
* Existing, imported-not-edited: `apps/invoice-fe/components/audit/PdfViewerCanvas.tsx` — reused as-is; rendering a PDF and its bounding boxes is direction-agnostic.
* New proxy route: `apps/invoice-fe/app/api/outbound-audit/resolve/[id]/route.ts` → `PUT /outbound-audit/resolve/{id}`.

### Functionality

**Tab visibility:** same rule as Ingestion — a small *Receiving*/*Sending* tab header, only shown when both Settings toggles are on; otherwise a single undivided view (today's Auditor if only Receive is on, or just the outbound console if only Send is on).

**`OutboundAlertConsole.tsx`:** renders the same alert-card visual style as `AlertConsole.tsx` (yellow alert banners, editable-field styling on click) for the alert types `feature_7.1` produces (`missing_required_field`, math/faithfulness mismatches, `duplicate_invoice_number`), plus a `due_date`-past-today follow-up banner for `SENT` invoices. Corrections use the same click-to-edit pattern as `EditableField` (Task 4.6), reused visually but wired to the new resolve endpoint.

**Standing-rule checkbox:** below the correction diff, one checkbox — *"Apply this as a standing rule for all future outbound invoices?"* — sends an extra `apply_as_standing_rule: true` flag in the `PUT /outbound-audit/resolve/{id}` payload. No sandbox, no Trainer deep-link — this is deliberately simpler than the inbound "suggested_rule" banner (Task 4.7), since there's no vendor-scoped rule to review before committing (see `feature_7.1` for the reasoning).

**`PdfViewerCanvas.tsx` reuse:** imported directly for the outbound document preview + coordinate overlay, pointed at a new PDF proxy route for the outbound invoice — zero changes to the component itself.

### Explicitly out of scope
- Any "want to save this as a rule?" banner styled after Task 4.7 — replaced entirely by the simpler standing-rule checkbox above.
- Line Items Table (FE Gap 10, still open on the inbound side) — not duplicated here; can be added to both consoles together later if built.

### Tasks
- [ ] **Task 4.1.1:** Build `OutboundAlertConsole.tsx` — alert rendering, editable corrections, standing-rule checkbox.
- [ ] **Task 4.1.2:** Build `app/invoices/outbound-review/[id]/page.tsx`, reusing `PdfViewerCanvas.tsx`.
- [ ] **Task 4.1.3:** Build the new resolve proxy route.
- [ ] **Task 4.1.4:** Add the *Receiving*/*Sending* tab header (shared implementation with `feature_3.1`'s tab, if built as one small shared piece — decide at implementation time).

### Verification Plan
* **Manual Verification:**
  - Correct a field without checking the standing-rule box; confirm only that invoice updates.
  - Correct a field with the box checked; confirm the next uploaded outbound invoice reflects the rule without further correction (cross-check against `feature_7.1`'s BE verification plan).
  - Confirm the existing `/invoices/review/[id]` page and `AlertConsole.tsx` are visually and functionally unchanged.
