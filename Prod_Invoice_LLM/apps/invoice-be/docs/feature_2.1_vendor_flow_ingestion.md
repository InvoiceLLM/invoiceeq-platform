# Feature 2.1: Service Flow — Outbound Invoice Ingestion ("Send Invoices") — **NOVA Agent**

**NOVA** (Smart Invoice Extraction) powers this flow. Extends [feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md). Spec only — no implementation yet, pending approval of the full Service Flow document set.

Adds the outbound half of invoice processing: instead of ingesting a vendor's invoice addressed *to* the tenant, this ingests the tenant's own invoice addressed *to their customer*. Upload-only — there is no in-app invoice creation/generation (that's a deliberately separate, deferred concern, see [feature_17_invoice_builder.md](feature_17_invoice_builder.md)) — and gated entirely behind the *Send Invoices* Admin-only toggle in [feature_16_settings.md](feature_16_settings.md).

### Design decision: a parallel pipeline, not a shared one

Reusing the existing extraction schema (`InvoiceExtractionSchema` in `agents/extraction_agent.py`) would require adding a `customer_name` field to it — a small edit, but still an edit to shipped, tested code. Per an explicit review decision, this was rejected in favor of true zero-touch: a **wholly separate schema, prompt, and graph module**, reusing only pure, already-reusable pieces (`utils/verification_tools.py`'s math/faithfulness checks, `handlers.py::_run_ocr()`) by import, never by edit.

### File Coordinates (planned)
* New agent module: `apps/invoice-be/agents/outbound_extraction_agent.py` — `OutboundInvoiceExtractionSchema`, its own extraction prompt, and a 2-node graph (`extract_node` → `verify_node`).
* New queue handler: `apps/invoice-be/queue_worker/outbound_handlers.py` — `handle_process_outbound_invoice()`.
* Existing, imported-not-edited: `apps/invoice-be/queue_worker/handlers.py::_run_ocr()`; `apps/invoice-be/utils/verification_tools.py` (all `verify_*` functions).
* Existing, one small edit: `apps/invoice-be/queue_worker/main_worker.py`'s task-dispatch — one new `elif` branch to route an outbound message to `handle_process_outbound_invoice()`.
* Model: `apps/invoice-be/models.py::Invoice` — new columns.
* New router: `apps/invoice-be/routers/outbound_invoices.py` — upload endpoint, confirm-send endpoint.

### Functionality

**Data model (additive only, one Alembic migration):**
- `Invoice.flow_direction: str` — default `"INBOUND"`; new value `"OUTBOUND"`. Every existing row is unaffected by the default.
- `Invoice.customer_name: str | None` — populated only for `OUTBOUND` rows.
- `Invoice.customer_id: UUID | None` — reserved for future customer-record linking; unused in v1 since no customer-facing portal exists yet.

**Pipeline:** Tenant uploads a PDF they authored elsewhere → `_run_ocr()` (imported, unmodified) extracts raw text/coordinates/confidence exactly as it does for inbound → `outbound_extraction_agent.py::extract_node` runs its own multimodal LLM call against `OutboundInvoiceExtractionSchema` (fields: `customer_name`, `invoice_number`, `invoice_date`, `due_date`, `grand_total`, `tax_amount`, `currency`, `items`, framed in the prompt as "this is the tenant's own invoice being sent to a customer") → `verify_node` runs the same imported math/faithfulness checks used inbound (`verify_totals_math`, `verify_grand_total_in_source_text`, etc.) against this document.

**v1 scope cut:** no classify/dynamic_qa split. That complexity exists inbound to handle unpredictable, unknown vendor layouts; a tenant's own invoices are one consistent, self-authored format, so a single extract→verify pass is sufficient for v1. Flagged as a deliberate cut, not an oversight — revisit if real-world outbound formats turn out to vary more than expected.

**Standing rules:** `extract_node` also queries the tenant's `OUTBOUND` Global `ExtractionTemplate` (new `flow_direction` column, see [feature_7.1_vendor_flow_auditor.md](feature_7.1_vendor_flow_auditor.md)) and injects it into the prompt — the outbound equivalent of Trainer's rule injection, but collapsed to Global-only with no sandbox, since there's no vendor variability to justify one.

**Status lifecycle** (new, distinct from inbound's `PROCESSING`/`COMPLETED`/`AUDIT_REQUIRED` since the semantics differ — this is pre-send validation, not post-receipt audit):
`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED / NEEDS_REVIEW → (tenant confirms) → SENT → PAID / OVERDUE`

**Ties into Auditor:** `NEEDS_REVIEW` invoices route to the new outbound Auditor screen ([feature_7.1_vendor_flow_auditor.md](feature_7.1_vendor_flow_auditor.md)) for correction before send — this is also where the backlog item "mirror the edit-and-capture requirement for outbound corrections" gets implemented, rather than as a separate effort.

### Explicitly out of scope
- Invoice generation/branding/templates (logo upload, layout picker) — separate feature, [feature_17_invoice_builder.md](feature_17_invoice_builder.md), not started.
- The actual email-send call — decided as email (via `Tenant.outbound_sender_email`, see [feature_16_settings.md](feature_16_settings.md)), reusing the ACS Email connection from [feature_14_email_ingestion.md](feature_14_email_ingestion.md) for sending. Wiring the confirm-send endpoint (Task 2.1.5) to actually place that call is part of this feature's build, not a separate one — listed here only to flag that the decision (email vs. download link vs. portal) is now made, closing what was previously an open question.
- AI Trainer rule scope for outbound — confirmed not applicable; extraction rules are a vendor/document-shape concern, and outbound documents aren't run through the Trainer's rule-resolution stage.

### Tasks
- [ ] **Task 2.1.1:** Add `flow_direction`, `customer_name`, `customer_id` columns to `Invoice` (Alembic migration, nullable/defaulted).
- [ ] **Task 2.1.2:** Build `agents/outbound_extraction_agent.py` — `OutboundInvoiceExtractionSchema`, extraction prompt, `extract_node`/`verify_node` graph.
- [ ] **Task 2.1.3:** Build `queue_worker/outbound_handlers.py::handle_process_outbound_invoice()`, importing `_run_ocr()` and `verification_tools.py` functions.
- [ ] **Task 2.1.4:** Add one `elif` branch to `main_worker.py`'s task dispatch for the new outbound message type.
- [ ] **Task 2.1.5:** Build `routers/outbound_invoices.py` — upload endpoint (enforces the *Send Invoices* Settings toggle is on) and a confirm-send endpoint (`VERIFIED`/corrected → `SENT`).

### Verification Plan
* **Manual Verification:**
  - With *Send Invoices* off in Settings, confirm the upload endpoint rejects outbound uploads.
  - Upload a clean, self-consistent outbound PDF; confirm it reaches `VERIFIED` with no alerts and extracted fields match the source document.
  - Upload an outbound PDF with a deliberately wrong total; confirm it lands on `NEEDS_REVIEW` with a faithfulness alert, and that existing inbound invoices/extraction are entirely unaffected (regression check on `tests/test_extraction.py`, `tests/test_ingestion.py`).
  - Confirm `main_worker.py`'s existing inbound dispatch path is unchanged — run an inbound upload through the queue worker and verify no behavior change.
