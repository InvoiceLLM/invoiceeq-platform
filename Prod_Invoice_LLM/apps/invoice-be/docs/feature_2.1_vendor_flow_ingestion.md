# Feature 2.1: Service Flow — Outbound Invoice Ingestion ("Send Invoices") — **NOVA Agent**

**NOVA** (Smart Invoice Extraction) powers this flow. Extends [feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md). **Built 2026-07-29** (see Tasks below) — previously unassigned to any of the Dashboard/Audit split devs, picked up as a hard prerequisite for Dev 2/Dev 3's outbound work once discovered they both silently depended on it.

Adds the outbound half of invoice processing: instead of ingesting a vendor's invoice addressed *to* the tenant, this ingests the tenant's own invoice addressed *to their customer*. Upload-only — there is no in-app invoice creation/generation (that's a deliberately separate, deferred concern, see [feature_17_invoice_builder.md](feature_17_invoice_builder.md)) — and gated entirely behind the *Send Invoices* Admin-only toggle in [feature_16_settings.md](feature_16_settings.md).

**Accepts images since Feature 28 (2026-09-04).** `POST /outbound-invoices/upload` takes PNG/JPG/TIFF/WEBP/BMP as well as PDF; `services/file_intake.py::normalize_upload()` converts at the door, ahead of the Gap 343 quota charge, so a refused file still burns nothing. See [feature_28_image_upload_pdf_boundary.md](feature_28_image_upload_pdf_boundary.md).

### Design decision: a parallel pipeline, not a shared one — ~~current~~ **reversed 2026-08-21 (Gap 283)**

**Original decision (2026-07-29), kept here for the record:** reusing the existing extraction schema (`InvoiceExtractionSchema` in `agents/extraction_agent.py`) would require adding a `customer_name` field to it — a small edit, but still an edit to shipped, tested code. Per an explicit review decision, this was rejected in favor of true zero-touch: a **wholly separate schema, prompt, and graph module**, reusing only pure, already-reusable pieces (`utils/verification_tools.py`'s math/faithfulness checks, `handlers.py::_run_ocr()`) by import, never by edit.

**What actually happened, and why this was reversed:** the separate *graph* is what went wrong, not the separate *schema*. Because outbound owned its own `extract_node`/`verify_node`, every inbound improvement made after 2026-07-29 had to be ported by hand — and mostly wasn't. By the time Gap 283 was opened the outbound path was missing `classify_node`, `dynamic_qa_node` (Gap 4), the bounded `verify → extract` retry loop (Gap 2/47), `verify_unit_prices_in_source_text` (Gap 44), the Doc Intelligence tax backfill, and Gap 70's `active_constraints` alert attribution. None of those nodes are direction-aware — they read `ocr_text`/`ocr_result`/`complexity` and generic numeric fields that exist identically on both schemas — so the zero-touch rationale bought nothing and cost six missed improvements. **The two directions now share one graph** in `agents/extraction_agent.py`, selected by `ExtractionState["flow_direction"]`. `OutboundInvoiceExtractionSchema` remains a genuinely separate model (that half of the original decision stands): a customer-addressed document really does have a different field set, and `outbound_handlers.py`/`routers/outbound_audit.py` are written against exactly it.

### File Coordinates
* Shared graph: `apps/invoice-be/agents/extraction_agent.py` — the one compiled `classify → dynamic_qa → extract → verify` `StateGraph`, plus `OutboundInvoiceExtractionSchema`, `OutboundInvoiceLineItem`, `build_outbound_multimodal_prompt()`, `_build_outbound_text_prompt()`, `_DirectionProfile`, `_DIRECTION_PROFILES`, `resolve_direction_profile()`.
* Outbound entry point: `apps/invoice-be/agents/outbound_extraction_agent.py` — **since Gap 283 a thin wrapper, not a graph**: `run_outbound_extraction_agent()` delegating to `run_extraction_agent(..., flow_direction="OUTBOUND")`, plus re-exports of the outbound schema/prompt names for existing callers.
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

**Pipeline (as of Gap 283, 2026-08-21):** Tenant uploads a PDF they authored elsewhere → `_run_ocr()` (imported, unmodified) extracts raw text/coordinates/confidence exactly as it does for inbound → `run_outbound_extraction_agent()` runs the **shared** graph with `flow_direction="OUTBOUND"`: `classify_node` scores complexity → `dynamic_qa_node` runs Gap 4's targeted structural pre-analysis if COMPLEX → `extract_node` makes the multimodal LLM call against `OutboundInvoiceExtractionSchema` (fields: `customer_name`, `invoice_number`, `invoice_date`, `due_date`, `subtotal`, `grand_total`, `tax_amount`, `currency`, `items`, `taxes`, framed in the prompt as "this is the TENANT'S OWN invoice, being sent to one of their customers") → `verify_node` runs the full inbound check set (`verify_line_items_math`, `verify_totals_math`, and all five source-text faithfulness checks) plus the outbound-only `missing_required_field` check → the conditional edge loops back to `extract_node` with the alert messages injected as feedback, bounded at `max_retries=2`, before settling on `VERIFIED`/`NEEDS_REVIEW`.

**~~v1 scope cut: no classify/dynamic_qa split~~ — reversed 2026-08-21 (Gap 283).** The original reasoning was that a tenant's own invoices are one consistent, self-authored format, so a single extract→verify pass would do. Two things made that wrong in practice: a tenant's "own" format still varies by tax regime (multi-slab GST, retention/holdback lines, e-invoicing compliance identifiers — exactly what `dynamic_qa_node` asks about), and, more importantly, owning a second graph is what caused outbound to silently miss six subsequent inbound improvements. Outbound now runs the identical node sequence. The one place the COMPLEX path is *not* mirrored verbatim: `_build_outbound_text_prompt` does not ask the model to fill `discounts[]`/`compliance_metadata[]`, because `OutboundInvoiceExtractionSchema` has no such fields. **Correction (2026-08-23, doc-accuracy pass):** an earlier version of this paragraph also listed `taxes[]` among the fields not asked for — that was wrong even at the time it was written. `OutboundInvoiceExtractionSchema` has always carried a `taxes: List[TaxItem]` field (`extraction_agent.py`, added specifically so a CGST+SGST-split outbound invoice can engage Gap 69's component-aware faithfulness fallback instead of failing verification on every genuine multi-line tax split), and `_build_outbound_text_prompt` does ask the model to fill it. Enriching the schema further (`discounts[]`, `compliance_metadata[]`, etc.) remains a deliberate follow-up, not part of Gap 283.

**Standing rules:** `extract_node` also queries the tenant's `OUTBOUND` Global `ExtractionTemplate` (new `flow_direction` column, see [feature_7.1_vendor_flow_auditor.md](feature_7.1_vendor_flow_auditor.md)) and injects it into the prompt — the outbound equivalent of Trainer's rule injection, but collapsed to Global-only with no sandbox, since there's no vendor variability to justify one.

**Status lifecycle** (new, distinct from inbound's `PROCESSING`/`COMPLETED`/`AUDIT_REQUIRED` since the semantics differ — this is pre-send validation, not post-receipt audit):
`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED / NEEDS_REVIEW → (tenant confirms) → SENT → PAID / OVERDUE`

**Ties into Auditor:** `NEEDS_REVIEW` invoices route to the new outbound Auditor screen ([feature_7.1_vendor_flow_auditor.md](feature_7.1_vendor_flow_auditor.md)) for correction before send — this is also where the backlog item "mirror the edit-and-capture requirement for outbound corrections" gets implemented, rather than as a separate effort.

### Explicitly out of scope
- Invoice generation/branding/templates (logo upload, layout picker) — separate feature, [feature_17_invoice_builder.md](feature_17_invoice_builder.md), not started.
- The actual staff email notification call — Gap 125 / Feature 14 Task 14.6 (SendGrid Mail Send to **registered** emails only; never customers). Confirm Send stamps SENT + optional `notify_emails[]` for AR staff. Tenant staff who *email the app* are on `TenantEmailSender.email_set='outbound'`.
- AI Trainer rule scope for outbound — confirmed not applicable; extraction rules are a vendor/document-shape concern, and outbound documents aren't run through the Trainer's rule-resolution stage.

### Tasks
- [x] **Task 2.1.1:** Add `flow_direction`, `customer_name`, `customer_id`, `sent_at`, `paid_at` columns to `Invoice` (migration `c4d5e6f7a8b9`). Bundled `sent_at`/`paid_at` in here too (Feature 8.1 Task 8.1.1) since this feature's own confirm-send endpoint needed `sent_at` immediately — avoided a second migration for one column. Also bundled `ExtractionTemplate.flow_direction` (Feature 7.1 Task 7.1.1) into the same migration, since it required reworking that table's unique constraints (see Task 7.1.1 in `feature_7.1_vendor_flow_auditor.md` for why).
- [x] **Task 2.1.2:** Built `agents/outbound_extraction_agent.py` — `OutboundInvoiceExtractionSchema` (customer_name/invoice_number/invoice_date/due_date/subtotal/grand_total/tax_amount/currency/items), `build_outbound_multimodal_prompt()`, 2-node graph (`extract_node` → `verify_node`, no classify/dynamic_qa per the v1 scope cut above). Reused `pdf_to_base64_images`/`invoke_with_retry`/`GAP_46_VERBATIM_DIRECTIVE` from `extraction_agent.py` by import.
  - **Stale line corrected 2026-08-21**: this used to claim `verify_node` "deliberately skips `verify_totals_math`/`verify_line_items_math` (both require a `subtotal` this schema doesn't have)". That stopped being true when Gap 223 added `subtotal` to the schema and wired both math checks in; the doc was never updated. Both have been running on the outbound path since Gap 223.
  - **Superseded 2026-08-21 by Gap 283.** The 2-node graph is gone. `agents/extraction_agent.py` now holds one `classify → dynamic_qa → extract → verify` graph shared by both directions, keyed on `ExtractionState["flow_direction"]`; `_DirectionProfile`/`_DIRECTION_PROFILES` enumerate everything that varies by direction (schema, `max_tokens`, both prompt builders, `required_fields`, the `VERIFIED`/`NEEDS_REVIEW` vs `COMPLETED`/`AUDIT_REQUIRED` status vocabulary, and the inbound-only legacy `"audit"`-in-filename shim). `outbound_extraction_agent.py` is now a 74-line wrapper: `run_outbound_extraction_agent()` calls `run_extraction_agent(..., flow_direction="OUTBOUND")` and re-exports the outbound schema/prompt names. `OutboundInvoiceExtractionSchema` itself moved into `extraction_agent.py` unchanged. Outbound thereby picked up classify, dynamic QA, the bounded retry loop, `verify_unit_prices_in_source_text`, the Doc Intelligence tax backfill and Gap 70 alert attribution. The `missing_required_field` check for `customer_name`/`invoice_number`/`grand_total` still exists and is still outbound-only — it is now `_DIRECTION_PROFILES["OUTBOUND"].required_fields`, consumed by the shared `verify_node`. See tracker Gap 283 for the full before/after and the two intentional outbound behaviour changes.
- [x] **Task 2.1.3:** Built `queue_worker/outbound_handlers.py::handle_process_outbound_invoice()` — mirrors `handle_process_invoice()`'s shape (OCR → extract → verify → DB update → SSE), single pass (no two-stage vendor rule resolution, since outbound rules are Global-only). `duplicate_invoice_number` check scoped per `customer_name` (the AR mirror of inbound's per-`vendor_name` duplicate check).
  - **Corrected 2026-08-17 — this line used to read "No RAG indexing — out of scope for ingestion", which went stale and was never updated.** RAG indexing *was* added to this handler by Feature 6.1 Task 6.1.3, gated on `status == "VERIFIED"` to mirror inbound's `COMPLETED` trigger.
  - **Gap 243 (fixed 2026-08-17)**: that `VERIFIED` gate was the outbound twin of Gap 240's inbound `COMPLETED` gate, and it failed worse. An outbound invoice landing `NEEDS_REVIEW` was never indexed, and — unlike inbound, where at least a status transition exists to hypothetically key on — `routers/outbound_audit.py::resolve_outbound_alert()` **never mutates `invoice.status` at all** (an outbound resolve is corrections plus alert dismissal only). There was therefore no status transition available even in principle, so a customer-facing invoice a human had to review could never become searchable, permanently. Now gated on the shared `chroma_client.should_index_status()`, the same predicate inbound uses, and `resolve_outbound_alert()` carries a backstop keyed on **the resolution happening at all** — probing `has_invoice_chunks()` first so the already-indexed case costs one cheap Chroma `get`, indexing with `customer_name` (matching how ingestion passes it through the `vendor_name` parameter), and never failing the human's resolve action if Chroma errors. See `feature_6_rag.md` for the shared design and `docs/test_evidence/gap244_rag_retrieval_2026-08-17/` for the measured before/after.
- [x] **Task 2.1.4:** Added `elif task_name == "process_outbound_invoice"` branch to `main_worker.py`'s dispatch, routing to `handle_process_outbound_invoice()`.
- [x] **Task 2.1.5:** Built `routers/outbound_invoices.py` — `POST /outbound-invoices/upload` (403 if `Tenant.send_invoices_enabled` is false, creates `Invoice` with `flow_direction="OUTBOUND"`/`status="UPLOADED"`, enqueues `process_outbound_invoice`) and `PUT /outbound-invoices/{id}/confirm-send` (`VERIFIED`/`NEEDS_REVIEW` → `SENT`, stamps `sent_at`; 400 on any other current status). Registered in `main.py`.

### Verification Plan
* **Automated Tests**: `uv run pytest tests/test_outbound_extraction.py tests/test_outbound_ingestion.py` — 18 tests: extraction agent (clean pass reaches `VERIFIED`, missing required field and unfaithful grand_total both reach `NEEDS_REVIEW`, token-limit short-circuit), upload endpoint (403 when Send Invoices disabled, 201 + correct DB row when enabled, 400 on non-PDF), confirm-send (`VERIFIED`→`SENT` and `NEEDS_REVIEW`→`SENT` both allowed, wrong-status 400, tenant isolation 404), and the queue handler (clean invoice reaches `VERIFIED`, duplicate detection by `customer_name` flags `NEEDS_REVIEW`, and — the one most worth calling out — a test asserting an tenant's *inbound* Global template's rules are never passed to the outbound extraction call, only the tenant's *outbound* Global template is, confirming the two rule sets don't cross-contaminate despite sharing the same `ExtractionTemplate` table).
* **Gap 243 regression coverage (2026-08-17)**: `tests/test_direction_aware_chat.py::test_needs_review_outbound_invoice_also_triggers_rag_indexing` (inverted from a prior test that asserted the buggy skip) and `::test_unextracted_outbound_invoice_is_not_rag_indexed` (the widened gate is still bounded — a FAILED extraction stays out), plus `tests/test_rag.py::test_outbound_resolve_backfills_rag_index_for_an_unindexed_invoice`.
* **Gap 283 regression coverage (2026-08-21)**: same two files, re-run unchanged in substance after the graph consolidation — `tests/test_outbound_extraction.py` (5) + `tests/test_extraction.py` (7) + `tests/test_verification_overrides.py` (9) = 21 passed, matching the baseline captured before any edit. Two mechanical test edits were needed: `test_outbound_extraction.py`'s `patch()` targets moved to `agents.extraction_agent.*` (the wrapper no longer owns `get_llm`/`check_token_guardrails` in its module globals; its `import`s still go through the wrapper so the re-exports stay covered), and `test_outbound_verify_node_gets_the_same_parameterization` now passes `flow_direction: "OUTBOUND"` — without it, the shared `verify_node` would have graded the INBOUND profile and the test would have kept passing for the wrong reason. Still fully mocked: no live Azure OpenAI/Document Intelligence call in any of it, so the outbound COMPLEX/dynamic-QA path has not been exercised against a real model or a real outbound PDF.
* **Manual Verification** (not yet done — no live BE/DB/real LLM in this pass, all tests run against mocked OCR/LLM + SQLite): the 4 manual checks originally listed here (Send-Invoices-off rejection, a real clean PDF reaching `VERIFIED`, a real wrong-total PDF reaching `NEEDS_REVIEW`, a real inbound upload confirming zero dispatch regression) still need to be run against a live `docker compose` stack with real Azure OCR/LLM calls before this is considered production-verified.

---

## Widened (2026-09-05) — the outbound schema now matches the `Invoice` model (BE Gap 467)

Additive section. Everything above stands as the record of how the outbound flow was built;
this records what changed, including where it makes an older sentence above stale.

### The problem, in one sentence

`OutboundInvoiceExtractionSchema` was **narrower than the `Invoice` row it writes to**. It
carried `customer_name`, `invoice_number`, both dates, `subtotal`/`tax_amount`/`grand_total`,
`currency`, `round_off`, `discount_percent`/`discount_amount`, `items` and `taxes` — and
nothing else. `InvoiceExtractionSchema` (INBOUND) carried, and `Invoice` had columns for,
seven more fields plus two per-line ones that outbound simply could not report.

Two consequences, both real rather than theoretical:

1. **A printed field was read and then discarded.** An outbound invoice with an address block,
   a PO number, a GSTIN, an IRN or a bank account printed on it stored none of them, because
   there was no schema key to put them in.
2. **The Invoice Builder's read-back check could not see them.** Gap 463 widened the builder to
   *print* all of these, and `verify_builder_readback()` deliberately excluded every one of
   them from its comparison — comparing against a key the reader never fills would have put
   every built invoice on `NEEDS_REVIEW` for a field nobody looked at. And because an OUTBOUND
   row left the columns empty, the builder's prefill had nothing to copy: a user who typed an
   address on a clone found that the *next* clone of that invoice could not inherit it.

### What changed

**Schema (`agents/extraction_agent.py`).** `OutboundInvoiceExtractionSchema` gains
`vendor_name`, `po_number`, `tax_ids`, `payment_instructions`, `references`, `addresses`,
`compliance_metadata` and `notes`; `OutboundInvoiceLineItem` gains `hsn_sac_code` and `uom`.

Every description except `notes` is **`InvoiceExtractionSchema`'s verbatim, not paraphrased** —
the rule already recorded on `ReferenceDocLineItem` and the reason for it: two descriptions of
one concept are how a model comes to populate them differently, and these two schemas are
routinely compared field-for-field. `vendor_name` reads correctly unchanged, because on the
tenant's own invoice the tenant *is* the vendor and `customer_name` is who it is addressed to.
`notes` has no inbound counterpart to mirror and is described as transcription-only, for the
same reason every figure on the schema is: a model asked to "summarise the terms" writes
something the invoice does not say.

All fields are Optional or default to an empty list, so every stored outbound extraction stays
valid and a document that prints none of this extracts exactly as it did before.

**This makes two sentences above stale, stated rather than left to be discovered.** The
Functionality section's field list for `extract_node` and the Gap 283 paragraph's "the one
place the COMPLEX path is not mirrored verbatim: `_build_outbound_text_prompt` does not ask the
model to fill `discounts[]`/`compliance_metadata[]`, because `OutboundInvoiceExtractionSchema`
has no such fields" both describe the pre-467 schema. `compliance_metadata` is now asked for
and now exists; `discounts[]`/`deductions[]` remain deliberately absent as *list* fields (the
top-level scalar `discount_percent`/`discount_amount` from Gap 293 are what outbound uses). The
follow-up that paragraph called "a deliberate follow-up, not part of Gap 283" is this gap.

**Prompt.** `_build_outbound_text_prompt`'s COMPLEX branch names the compliance/banking lists
the way the inbound COMPLEX prompt does. That is the whole prompt change: the **schema is the
contract**, its field descriptions are what drive structured output, and no rule that decides
correctness lives in prompt text (CONVENTIONS hard rule 3).

**Persistence (`queue_worker/outbound_handlers.py`).** The handler now writes
`vendor_name`, `po_number`, `notes`, `tax_ids`, `payment_instructions`, `references`,
`addresses` and `compliance_metadata` onto the row — the same columns, in the same shape, with
the same `get(..., default)` behaviour as the inbound block in `queue_worker/handlers.py`, so
one field cannot mean two things depending on which door the document came through.

`notes` is the one exception to "plain write": it is `extracted_data.get("notes") or
invoice.notes`, because the **builder** already stamped the notes block it printed at creation
time, and a model that did not return a free-text block is not evidence the invoice has none.
On an upload the column is NULL at that point, so it is a plain write there.

**New column.** `Invoice.notes: str | None`, nullable, migration `e7f8a9b0c1d2` (one
`add_column`, no backfill — founder ruling 2026-09-05: dev environment, dev phase, no existing
data is migrated). NULL means "no notes block was read", never "the invoice printed none".

### The consequence of populating `vendor_name` on an OUTBOUND row — and the two guards it needed

This is the Gap 329 shape: a column that used to be INBOUND-only in practice starts carrying
OUTBOUND rows, and every query that reads it without a `flow_direction` filter silently
changes meaning. Two sites were unfiltered and were fixed in the same change:

| Site | Why it mattered | Fix |
|---|---|---|
| `routers/trainer.py::list_trainer_vendors` | The Existing-Vendor picker would have offered the tenant **their own name** as a vendor to train an extraction template against. | `flow_direction == "INBOUND"` |
| `queue_worker/handlers.py`, the Layer-2 duplicate check | A bill *received* is never a duplicate of an invoice *issued*; a self-billing tenant could have an outbound row flag an inbound one. | `flow_direction == "INBOUND"` |

The inbound dashboard (`routers/dashboard.py`), the inbound invoice list (`routers/invoices.py`)
and `services/rule_impact.py` were already filtered — Gap 329's own fix. Read sites that
deliberately stay unfiltered: `routers/audit.py`'s display join and `agents/query_agent.py`'s
tenant-wide distinct-vendor count and name search, all of which are direction-agnostic by
intent.

### Verification (real Postgres, `localhost:5433/invoice_db`, 2026-09-05)

`pytest tests/test_outbound_extraction.py -q` → **`13 passed in 5.67s`** (3 new: the schema
covers every field the inbound one does and mirrors its descriptions verbatim; every widened
field stays Optional; the widened fields reach `extracted_data` through the real graph).

`pytest tests/test_outbound_ingestion.py tests/test_trainer.py tests/test_chat_attachments.py
tests/test_direction_aware_chat.py tests/test_extraction_benchmark.py
tests/test_invoice_reconciliation.py -q` → **`256 passed, 1 skipped in 25.49s`**.

The builder half, including the end-to-end clone-of-a-clone proof, is recorded in
[feature_17_invoice_builder.md](feature_17_invoice_builder.md) § "Read back and inherited".
