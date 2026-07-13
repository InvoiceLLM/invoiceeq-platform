# Feature 2: Ingestion, Storage & Extraction Pipeline

Accept PDF uploads, persist them to Azure Blob Storage, queue background processing, and run the multi-modal LLM extraction + math verification agent to produce structured invoice data.

*(Merged 2026-07-13 from the former "Feature 2: Ingestion & Storage Pipeline" and "Feature 5: Multi-Modal Extraction & Verification Agent" docs — upload → OCR → extraction → verification → indexing is one continuous request-to-completion flow with no natural seam between them; see Pipeline Flow below.)*

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py)
* Database Models: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)
* Background Worker: [apps/invoice-be/workers/tasks.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/workers/tasks.py)
* Extraction Agent: [apps/invoice-be/agents/extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py)
* Math Validator: [apps/invoice-be/utils/verification_tools.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/verification_tools.py)
* Token Guardrails: [apps/invoice-be/utils/token_management.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/token_management.py)
* RAG Indexer: [apps/invoice-be/chroma_client.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/chroma_client.py)
* Blob Storage Helper: [apps/invoice-be/services/storage.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/services/storage.py)
* Invoice Complexity Classifier (planned, not yet built — see Task 2.12 / tracker Gap 1): `apps/invoice-be/services/invoice_classifier.py`

### Pipeline Flow (folder → file → function → functionality)
1. `routers/invoices.py` → `POST /upload`:
   - Fetches the `Tenant` row for `context.tenant_id`; if none exists, **silently auto-provisions one** with a placeholder domain (`domain-{tenant_id}.com`) — an undocumented fallback that bypasses the real domain-based tenant provisioning flow (Website Feature 4 / Clerk gateway). See Task 2.19 / tracker Gap 25.
   - Enforces free-plan limits, then per file: computes a SHA-256 `file_hash` and checks it against existing `Invoice` rows for that tenant. **Exact-hash duplicate detection (Layer 1) is already implemented** — a hash match creates a `status=DUPLICATE` row copying the prior extraction's data and publishes a `DUPLICATE` SSE event immediately, skipping re-processing. Near-duplicate matching (Layer 2 — same `invoice_number` + `vendor_name` with a different file hash, e.g. a rescanned copy) is not implemented. See Task 2.20 / tracker Gap 9.
   - For non-duplicate files: uploads bytes to Blob Storage, inserts `Invoice` row (`status=PROCESSING`), enqueues Celery task, returns `batch_id`. ⚠️ This upload call is currently broken — see Task 2.18 / tracker Gap 24 (P0).
2. `workers/tasks.py` → `process_invoice_task(batch_id, file_path, tenant_id)` — the pipeline orchestrator. Sequence:
   - `_publish_sse_events()` → emits `PROCESSING_OCR` over Redis pub/sub (channel `invoice.update.{batch_id}`), consumed by the FE `EventSource`/polling.
   - `_run_ocr(file_path, settings)` → local `pypdf` text extraction (Ollama/dev) or Azure Document Intelligence `prebuilt-layout` (prod — see Task 2.14 / tracker Gap 15 to switch this to `prebuilt-invoice`).
   - `_publish_sse_events()` → emits `EXTRACTING_DATA`.
   - Looks up a per-vendor layout template: queries `ExtractionTemplate` table by `(tenant_id, vendor_name)`, else falls back to `config/default_templates.json`.
   - Calls `agents/extraction_agent.py::run_extraction_agent()` (first pass with no rules; re-run with template `rules` if a vendor match is found) — see "Extraction Agent Internals" below.
   - Writes extracted fields, `sa_alerts`, and `status` (`COMPLETED` / `AUDIT_REQUIRED`) back onto the `Invoice` row.
   - If `status == COMPLETED`: `_publish_sse_events()` emits `INDEXING`, then `chroma_client.index_invoice_document()` chunks the document and writes vector embeddings for RAG.
   - `_publish_sse_events()` → emits final status (`COMPLETED` / `AUDIT_REQUIRED` / `FAILED`) with the extracted data and alerts payload.
3. `workers/tasks.py` → `import_connector_file_task(provider, file_id, tenant_id)` — third-party connector variant (Google Drive / Salesforce): downloads the source file, uploads it via `services/storage.py`, creates the `Invoice` row, then synchronously calls `process_invoice_task()` to re-enter the same flow as step 2.

### Extraction Agent Internals (LangGraph)
`run_extraction_agent()` compiles and runs a 2-node `StateGraph`:
* `extract_node` — LLM call via `utils/llm.py::get_llm()`, wrapped with `.with_structured_output(InvoiceExtractionSchema)`. Fed OCR text plus base64-encoded page images (`pdf_to_base64_images()`) for multi-modal table/column layout mapping. Falls back to `get_fallback_extracted_data()` (mocked data) if the LLM call fails or returns an unparseable shape — see Task 2.13 / tracker Gap 19, this is a live correctness bug, not just a design gap.
* `verify_node` — **the math validator**, no LLM involved. Calls `utils/verification_tools.py::verify_line_items_math()` (`sum(items.amount) == subtotal`) and `verify_totals_math()` (`subtotal + tax_amount == grand_total`). Mismatches are appended to `sa_alerts` and flip `status` to `AUDIT_REQUIRED`.

Before either node runs, `check_token_guardrails()` (`utils/token_management.py`) pre-flight-checks estimated prompt tokens against the model's context limit and short-circuits straight to `AUDIT_REQUIRED` with a `token_limit_exceeded` alert if it would overflow.

Still missing entirely: complexity-based routing (extract vs. dynamic-parse), a critique/retry loop, bounding-box coordinates, field-level confidence, and per-line tax/discount math — each broken out as its own task below since they're independent build efforts, not one graph change.

### Schema Extensibility Goal (Tasks 2.21, 2.23–2.31)
What we're trying to achieve with this batch of schema work: today, encountering an invoice element the schema doesn't have a field for (a new tax type, a new bank-detail format, an unfamiliar reference number) means it's either silently dropped or mis-stuffed into the wrong field — and fixing it requires a code change and a deploy. These tasks add **list-shaped fields** (`taxes[]`, `references[]`, `tax_ids[]`, etc.) instead of one-off scalar fields, so that once the *shape* exists, recognizing a **new specific value within it** becomes a trainer-taught rule (Global scope, per `feature_10_trainer.md`) instead of a schema migration.

Two different guarantees, depending on the field:
- **Descriptive lists** (`tax_ids[]`, `payment_instructions[]`, `references[]`, `addresses[]`, `compliance_metadata[]`) — nothing computes off these. Once the list exists, a trainer rule can teach recognition of any new country-specific variant (a new tax-ID format, a new e-invoicing compliance code) with **zero code changes, ever again**.
- **Calculation lists** (`taxes[]`, `discounts[]`, `deductions[]`) — a trainer rule can safely teach a *new value* flowing through the list (e.g. "GST" as a `tax_type`), but the arithmetic that consumes the list (Task 2.22) stays fixed in code — a rule should never be able to silently change how totals are calculated.

Net effect once this lands: an Indian GST invoice, a US multi-jurisdiction sales-tax invoice, and a European VAT invoice with reverse-charge notation all extract correctly through the *same* schema, without special-casing any of them in code.

### Tasks
- [x] **Task 2.1: Implement Ingestion Router Endpoint**
  - Implement `POST /api/v1/invoices/upload` accepting single/multiple PDF files.
  - Generate a unique `batch_id` for each session.
  - Configure the route parameter to accept an optional `tags` array parameter from the form.
- [x] **Task 2.2: Persist Files to Azure Blob Storage**
  - Initialize the Azure Blob Storage client from credentials.
  - Upload the raw binary stream to a tenant-isolated storage container folder structure: `tenants/{tenant_id}/invoices/{invoice_id}.pdf`.
- [x] **Task 2.3: Create Processing DB Entry**
  - Insert a record into the `invoices` table with status `PROCESSING` and the associated tags payload.
  - Return the generated `batch_id` and the database `job_ids` in the HTTP response.
- [x] **Task 2.4: Dispatch Celery Extraction Task**
  - Enqueue the extraction job `process_invoice_task` in the Celery queue.
  - Pass parameter identifiers: `batch_id`, `file_path`, and `tenant_id`.
- [x] **Task 2.5: Enforce Free Plan 50 Invoice limit**
  - Check the tenant's remaining invoices before creating records. If `billing_plan == 'free'` and `free_invoices_remaining <= 0`, raise `HTTPException(402, "Limit reached")`.
  - Decrement the count `free_invoices_remaining = free_invoices_remaining - 1` upon successful upload.
- [x] **Task 2.6: Update SQLModel Schema with Optional Columns**
  - Update `models.py` class `Invoice` to define new optional fields: `invoice_number: str | None = Field(default=None)`, `invoice_date: date | None = Field(default=None)`, `due_date: date | None = Field(default=None)`, `tax_amount: float | None = Field(default=None)`, `po_number: str | None = Field(default=None)`, `tags: list | None = Field(default=[], sa_column=Column(JSONB))`, and `items: list | None = Field(default=[], sa_column=Column(JSONB))`.
- [x] **Task 2.7: Construct LangGraph State Graph**
  - Define node states and transitions for the Extraction Agent using LangGraph (`extract` → `verify`).
  - Implement Pydantic structured output mapping (`LLM.with_structured_output()`) to guarantee layout matching.
- [x] **Task 2.8: Build Multi-Modal visual channel processing**
  - Convert PDF pages into base64 visual image strings to support table/column layout mapping.
  - Pipe visual streams and OCR text layout content into the agent model.
- [x] **Task 2.9: Implement Calculation Check Tools**
  - Code mathematical check tools: `verify_line_items_math` confirming `sum(line_items.amount) == subtotal`.
  - Validate that `subtotal + tax_amount == grand_total`.
- [x] **Task 2.10: Enforce Flag Warnings & Alerts System**
  - Save warnings to the database `sa_alerts` JSONB array column as structured objects containing details: `{"type": "tax_mismatch", "message": "...", "field": "tax_amount"}`.
  - Mark matching database invoices as `AUDIT_REQUIRED` if validation checks fail, or `COMPLETED` if they pass.
- [x] **Task 2.11: Implement Token Management & Pre-Flight Guardrails**
  - Count OCR text tokens with `tiktoken` and base64 image tokens matching model visual pricing detail levels.
  - Assert that estimated prompt + expected output length is within the model context limit (`check_token_guardrails`).
  - Gracefully redirect to `AUDIT_REQUIRED` with a `token_limit_exceeded` alert if guardrails are violated, bypassing the LLM.
  - Log token usage metrics alongside `tenant_id` for cost tracking.
- [ ] **Task 2.12: Complexity Classification Routing** *(tracker Gap 1)*
  - Add `services/invoice_classifier.py`: score each invoice's complexity from tax/discount indicators, additional-charge line presence, and layout structure signals sourced from Azure Document Intelligence's layout output (currently discarded — only `.content` text is used, see Pipeline Flow step 2).
  - Route "standard" invoices through the existing fixed `InvoiceExtractionSchema` prompt; route flagged non-standard invoices to a dynamic-parsing prompt path that doesn't force the fixed schema.
  - Wire the classifier's decision into `extract_node` (or a new node before it) in the LangGraph graph above.
- [ ] **Task 2.13: Remove fallback fake data** *(tracker Gap 19 — P0 correctness bug, not a feature)*
  - `extract_node`'s `get_fallback_extracted_data()` returns a hardcoded mock invoice (`ACME Corporation`, subtotal 150 / tax 15 / grand_total 165) whenever the LLM call fails or returns an unparseable shape, and that fake data is persisted as if it were a real extraction.
  - The mock numbers are internally consistent, so `verify_node`'s math checks pass and the invoice is marked `COMPLETED` with fabricated vendor/amount data and zero alerts — indistinguishable from a genuine successful extraction.
  - Replace the silent fallback with an explicit `extraction_failed` alert that always routes to `AUDIT_REQUIRED`; a failed extraction must never flow through as `COMPLETED`.
- [ ] **Task 2.14: OCR model switch** *(tracker Gap 15)*
  - Call Azure Document Intelligence with `model_id="prebuilt-invoice"` in `workers/tasks.py::_run_ocr()` instead of `prebuilt-layout`. It returns structured fields, bounding boxes, and per-field confidence scores natively — cutting image/token volume sent to the LLM and giving a reliable, non-hallucinated source for Tasks 2.15 and 2.17 below (an LLM asked to output pixel coordinates in a structured-output call is not a reliable source for them). Solves Gap 16/Gap 17 for free.
- [ ] **Task 2.15: Bounding-box coordinates** *(tracker Gap 16 — closes a currently-broken FE feature, not new scope)*
  - Add a `coordinates` field to `InvoiceExtractionSchema` and a matching `coordinates` JSONB column on `Invoice`, sourced from the Task 2.14 `prebuilt-invoice` output.
  - `fe_features/feature_4_auditor.md` Task 4.2 is already marked complete and ships `PdfViewerCanvas.tsx` reading `invoice.coordinates[]` — today that field is always empty since nothing on the backend populates it, so the shipped overlay is non-functional. This task makes that existing FE code work rather than adding new UI.
- [ ] **Task 2.16: Extract → critique → retry loop** *(tracker Gap 2 + Gap 3 — Evaluator Router + Critic Node)*
  - Implement an Evaluator Router and Critic Node in the LangGraph graph: on `verify_node` failure, route back to `extract_node` with the specific mismatch as feedback, bounded to N retries, before falling through to `AUDIT_REQUIRED`.
  - Reduces manual audit volume by letting the agent self-correct simple LLM misreads instead of escalating every math mismatch to a human.
- [ ] **Task 2.17: Field-level confidence scores** *(tracker Gap 17)*
  - Populate a `field_confidence` map per extracted field (sourced from Task 2.14's `prebuilt-invoice` output where available) so low-confidence fields can be flagged individually and drive Task 2.16's Critic Node.
  - No standalone value without a consumer: pair this with either Task 2.16 (route only low-confidence fields back for retry) or a simpler direct FE affordance (highlight low-confidence fields yellow for the auditor) — decide which before implementing.
- [ ] **Task 2.18: Fix P0 upload crash bug** *(tracker Gap 24 — confirmed live in code, highest priority in this file)*
  - [routers/invoices.py:157-159](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py): `file_path = await run_in_threadpool(upload_pdf_to_blob_storage(file_bytes, str(context.tenant_id), str(invoice_id)))` calls `upload_pdf_to_blob_storage(...)` synchronously and passes its **return value** (a string) into `run_in_threadpool`, which then tries to call that string — raising `TypeError: 'str' object is not callable`.
  - Every non-duplicate PDF upload crashes with a 500 today.
  - Fix: `run_in_threadpool(upload_pdf_to_blob_storage, file_bytes, str(context.tenant_id), str(invoice_id))` — pass the callable and its args separately.
- [ ] **Task 2.19: Consolidate tenant auto-provisioning** *(tracker Gap 25)*
  - Remove the undocumented bare-`Tenant`-row fallback in `routers/invoices.py` (Pipeline Flow step 1) once the real domain-matching/role-assignment login flow (Website Feature 4) is live, so there's a single tenant-creation path instead of two that can diverge.
- [ ] **Task 2.20: Layer-2 duplicate detection** *(tracker Gap 9)*
  - Extend the existing SHA-256 exact-hash check (Pipeline Flow step 1, already implemented) with a post-extraction fuzzy match on `invoice_number` + `vendor_name`, catching re-scanned/re-saved copies that hash differently but represent the same invoice.
- [ ] **Task 2.21: Add structured `taxes` list to the extraction schema** *(tracker Gap 18 — triggered by: VAT invoices are showing up and aren't recognized at all today)*
  - Add `taxes: List[{tax_type: str, rate_percent: float | None, amount: float}]` to `InvoiceExtractionSchema` and a matching `taxes` JSONB column on `Invoice`, alongside (not replacing, for backward compat) the existing flat `tax_amount`. VAT is just the first `tax_type` value flowing through this — GST, CGST/SGST, sales tax, etc. need no further schema changes once this lands.
  - Add per-line and invoice-level `discount_percent`/`discount_amount` fields at the same time — same redesign, same migration.
  - This is a prerequisite for Task 2.22 below, and for the Global-scope trainer rule described in `feature_10_trainer.md` ("VAT is a tax item, applied after discount") — a trainer rule has nowhere to write VAT recognition into until this field exists (LLM structured-output extraction is bound to the schema; a prompt rule cannot invent a new field at runtime).
- [ ] **Task 2.22: Per-line-item tax/discount math** *(tracker Gap 18 — depends on Task 2.21, don't start before it lands)*
  - Extend `verify_line_items_math`/`verify_totals_math` beyond flat `subtotal`/`tax_amount`/`grand_total` to `qty × rate × (1 − discount) × (1 + tax)` per line, using the `taxes`/discount fields added in Task 2.21. Fixed calculation order (discount applied before tax) lives here in code — not something a trainer rule should be able to redefine.
- [ ] **Task 2.23: Generalize `discounts[]` from scalar fields to a list**
  - Replace the flat `discount_percent`/`discount_amount` fields (Task 2.21) with `discounts: List[{discount_type: str, percent: float | None, amount: float}]`. Achieves: multiple stacked discounts on one invoice (trade discount + early-payment discount + promo code) captured distinctly instead of collapsed into one number — matters once Task 2.22's math needs to know which discount applied where.
- [ ] **Task 2.24: Add `deductions[]` list**
  - `List[{deduction_type: str, amount: float}]` — retention/holdback (construction industry, held back until project completion) and advance-payment-already-received adjustments. Achieves: these subtract from the amount due like a discount but aren't a price reduction, so the math validator (Task 2.22) can treat them correctly instead of misreading them as a discount or ignoring them.
- [ ] **Task 2.25: Add `tax_ids[]` list**
  - `List[{id_type: str, value: str, party: "vendor" | "buyer"}]`. Achieves: captures India's GSTIN/PAN, EU VAT registration numbers (format varies per country — Germany's USt-IdNr, France's SIRET), and the US EIN — for both the vendor and the buyer, which the schema currently captures for neither. Purely descriptive — no math depends on it, so any new tax-ID format a trainer sees becomes a rule, not a schema change.
- [ ] **Task 2.26: Add `payment_instructions[]` list**
  - `List[{method_type: str, details: str}]`. Achieves: recognizes IBAN+SWIFT/BIC (Europe), ACH routing+account number (US), and UPI ID + IFSC code (India) without needing a dedicated field per country's banking format.
- [ ] **Task 2.27: Add `references[]` list**
  - `List[{ref_type: str, value: str}]`. Achieves: captures secondary document links beyond the existing dedicated `po_number` field — Sales Order number, India's e-Way Bill number (mandatory for goods movement above a threshold value), and credit/debit note references when an invoice amends another.
- [ ] **Task 2.28: Add `addresses[]` list**
  - `List[{address_type: "billing" | "shipping" | "vendor", text: str, country: str | None}]`. Achieves: captures a ship-to address distinct from billing/vendor address, which matters for goods invoices — especially India, where ship-to ties directly to the e-Way Bill reference from Task 2.27.
- [ ] **Task 2.29: Add `compliance_metadata[]` list**
  - `List[{key: str, value: str}]`. Achieves: future-proofs against country-specific e-invoicing mandates without a schema change each time one appears — India's IRN + QR code (mandatory e-invoicing), EU Peppol electronic address, Italy's SDI code. New countries add new mandates faster than schema PRs can keep up; this is the field designed to absorb that without code changes.
- [ ] **Task 2.30: Add `currency` field**
  - `currency: str | None` (ISO 4217 code, e.g. `INR`/`EUR`/`USD`) on both `InvoiceExtractionSchema` and `Invoice`. Achieves: removes the ambiguity of `grand_total: 150.0` meaning nothing on its own once vendors span multiple regions — a scalar field, not a list, but currently missing entirely.
- [ ] **Task 2.31: Add per-line-item `hsn_sac_code` / `uom` fields**
  - Add `hsn_sac_code: str | None` and `uom: str | None` to `InvoiceLineItem`. Achieves: India's GST invoices require an HSN/SAC code per line item by law; unit-of-measure (each/kg/hours) varies especially between goods and service invoices and is needed to sanity-check `quantity × unit_price = amount`.

### Verification Plan
* **Automated Tests**:
  - Execute `uv run pytest tests/test_ingestion.py` testing file uploads.
  - Execute `uv run pytest tests/test_extraction.py` to verify math checks, token limits, and DB persistence.
  - Run `uv run pytest` to check for zero regressions, ensuring compatibility with `test_sse.py`'s `"audit"` file path trigger.
* **Manual Verification**:
  - Run `docker compose up -d` to spin up local Redis/Postgres/ChromaDB. Upload a mock PDF to the router and check that the Celery task receives it.
  - Run extraction on test PDFs and inspect generated database alerts.
