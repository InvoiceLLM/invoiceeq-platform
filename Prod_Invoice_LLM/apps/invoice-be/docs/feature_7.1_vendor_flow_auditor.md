# Feature 7.1: Service Flow — Outbound Auditor (pre-send validation + standing rules)

Extends [feature_7_audit.md](feature_7_audit.md). Spec only — no implementation yet, pending approval of the full Service Flow document set.

Reviews `NEEDS_REVIEW` outbound invoices (produced by [feature_2.1_vendor_flow_ingestion.md](feature_2.1_vendor_flow_ingestion.md)'s verify step) before they can be marked `SENT`, surfaces `SENT` invoices past their `due_date` for follow-up, and — new, folded in during design review — lets a correction be taught back as a standing rule for all future outbound invoices.

### File Coordinates (planned)
* New router: `apps/invoice-be/routers/outbound_audit.py` — `PUT /outbound-audit/resolve/{id}`.
* Model: `apps/invoice-be/models.py::ExtractionTemplate` — one new additive column.
* Existing, imported-not-edited: `apps/invoice-be/models.py::ExtractionTemplateVersion` (history/rollback), same table Trainer already uses.
* Existing, unmodified: `apps/invoice-be/routers/trainer.py`, `apps/invoice-be/routers/audit.py` — neither is touched or extended; this is a deliberately separate, smaller mechanism (see design note below).

### Functionality

**Alert types** — produced by `outbound_extraction_agent.py::verify_node` ([feature_2.1](feature_2.1_vendor_flow_ingestion.md)), same `{"type", "message"}` shape as inbound, stored in the same `Invoice.sa_alerts` column: `missing_required_field`, math/faithfulness mismatches (via the imported `verification_tools.py` checks), `duplicate_invoice_number` (scoped per `customer_name` rather than per `vendor_name`).

**Overdue detection (v1 choice):** computed at read-time — `status == "SENT" and due_date < today()` surfaces the invoice as needing follow-up in the outbound Auditor list. Not persisted via a new scheduled job; a `main_worker.py`-driven periodic sweep can be added later if a truly persisted `OVERDUE` status turns out to be needed for reporting.

**Resolve endpoint:** `PUT /outbound-audit/resolve/{id}` in a new file, not importing from `routers/audit.py` — that file's resolve logic isn't factored into reusable pieces, and extracting a shared helper would itself be an edit to shipped code. The corrections-dict → update `Invoice` → `AuditLog` diff logic is duplicated in the new file; accepted price for zero-touch, consistent with the rest of Service Flow.

**Deliberately not included:** the Gap 27-style "detect a recurring pattern → suggest a rule → deep-link to Trainer" flow. That exists inbound because Trainer's Existing/New Vendor scopes can act on the suggestion; outbound has no such scope (see below for what it gets instead).

### Outbound Global Rules — a standing correction, not a Trainer session

Design conclusion from review: full 3-scope Trainer (Global/Existing Vendor/New Vendor) doesn't fit outbound — there's no vendor variability, since every outbound invoice is the tenant's own single, consistent template. But that same fixed template can still have a systematic misread (e.g., extraction always reads the wrong address block as `customer_name`), and because it's the *same* format every time, a standing fix is worth more here than inbound's per-vendor rules are individually.

Rather than reuse Trainer's sandbox UI (which would mean editing `trainer.py`/`ScopeSelector.tsx` to add a 4th scope) or build a parallel sandbox, this is collapsed to its simplest form:

- `ExtractionTemplate` gets one additive column: `flow_direction: str` (default `"INBOUND"`). An outbound rule is a row with `flow_direction="OUTBOUND"`, `vendor_name=NULL` — Global-only, no vendor field needed.
- `outbound_extraction_agent.py::extract_node` queries this tenant's `OUTBOUND` Global template by import (same pattern as inbound's `_get_template_rules()`), injecting it into the extraction prompt. Zero edits to Trainer's existing query logic — this is a new query, in a new file.
- **No sandbox, no chat-based refinement, no re-audit fan-out.** When resolving a `NEEDS_REVIEW` outbound invoice, the correction UI shows one checkbox: *"Apply this as a standing rule for all future outbound invoices?"* Checking it writes directly to `ExtractionTemplate` (new row or version bump via the existing, imported `ExtractionTemplateVersion` table) — no "try before commit" step, because there's no vendor variability to de-risk against; it's always the same one document format.
- History/rollback reuses `ExtractionTemplateVersion` (imported, not edited).

### Explicitly out of scope
- Vendor-style (per-customer) rule scoping — rejected; there's no format variability per customer to justify it.
- Persisted `OVERDUE` status / scheduled sweep job — deferred, v1 computes it at read-time only.

### Tasks
- [ ] **Task 7.1.1:** Add `flow_direction` column to `ExtractionTemplate` (Alembic migration, additive).
- [ ] **Task 7.1.2:** Build `routers/outbound_audit.py::resolve_outbound_alert()` — corrections capture, `AuditLog` diff, no pattern-detection/suggestion logic.
- [ ] **Task 7.1.3:** Add the "apply as standing rule" checkbox path — on check, upsert the tenant's `OUTBOUND` Global `ExtractionTemplate` row and write an `ExtractionTemplateVersion` entry.
- [ ] **Task 7.1.4:** Read-time overdue computation in the outbound Auditor list query.
- [ ] **Task 7.1.5:** Wire `outbound_extraction_agent.py::extract_node` to query and inject the `OUTBOUND` Global template.

### Verification Plan
* **Manual Verification:**
  - Correct a field on a `NEEDS_REVIEW` outbound invoice without checking the standing-rule box; confirm only that invoice's data changes, no `ExtractionTemplate` row is created.
  - Repeat with the box checked; confirm a new `OUTBOUND` Global template row (or version bump) exists, and that the *next* uploaded outbound invoice's extraction reflects the rule without any further correction.
  - Confirm inbound Trainer's Global/Existing Vendor/New Vendor scopes and `ScopeSelector.tsx` are completely unaffected — no new scope appears, no existing endpoint changes behavior.
  - Confirm a `SENT` invoice with a past `due_date` appears in the outbound Auditor's follow-up list, and a `SENT` invoice with a future `due_date` does not.
