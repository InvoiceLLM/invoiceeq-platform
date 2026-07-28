# System Journey — Developer Guide

Purpose: a single narrative walkthrough of how an invoice actually moves through this codebase, module by module — for review before the Service Flow build starts, not a replacement for `Technical_Architecture_Document.md` or the per-feature `feature_N_*.md` specs (which remain the source of truth for exact task numbers and status).

Marking convention used throughout:
- **[LIVE]** — exists, running, verified in this repo today.
- **[PLANNED]** — part of the Service Flow design discussed but not yet built; included here so the target end-state can be reviewed as one continuous journey, not two disconnected documents.

---

## Part 1 — The journey of an inbound invoice today [LIVE]

### 1. It arrives — Ingestion
A user uploads a PDF on the Ingestion screen. `routers/invoices.py`'s upload endpoint streams the file to Azure Blob Storage (`services/storage.py::upload_pdf_to_blob_storage`), computes a SHA-256 hash for Layer-1 duplicate detection, creates an `Invoice` row (`status="PROCESSING"`), and pushes one message onto the Azure Storage Queue `extraction-tasks-queue`. The user never talks to the extraction pipeline directly — everything past this point is asynchronous.

### 2. A worker picks it up
`queue_worker/main_worker.py` polls the queue in a loop, dispatching messages to a thread pool. Per-tenant fair-share throttling (`_acquire_tenant_slot`/`_release_tenant_slot`, Redis-backed) stops one tenant's batch upload from starving every other tenant's queue. `handle_process_invoice()` in `queue_worker/handlers.py` is the actual entry point for one invoice's processing.

### 3. OCR
`handlers.py::_run_ocr()` calls Azure Document Intelligence's `prebuilt-invoice` model (or local `pypdf` text extraction in Ollama/dev mode). Real-world transient connection errors get a bounded retry with exponential backoff, rotating across all 3 configured Doc Intelligence resources on each retry. The result includes raw text, per-field OCR confidence scores, and bounding-box coordinates for the PDF viewer overlay.

### 4. The extraction agent graph
`agents/extraction_agent.py` runs a LangGraph state machine:
- `classify_node` — STANDARD vs COMPLEX, via `services/invoice_classifier.py` (keyword/field-presence heuristics).
- `dynamic_qa_node` — COMPLEX invoices only. A pre-analysis LLM pass asking document-specific questions (multi-rate tax, holdbacks, e-invoicing identifiers) before the main extraction call, to ground it.
- `extract_node` — the real Azure OpenAI (`gpt-5-mini`) multimodal call, given OCR text + page images + any Trainer-taught rules (see step 6).
- `verify_node` — the critic. Runs math checks (`verify_totals_math`, per-line-item tax/discount), faithfulness checks against the raw OCR text (grand total / subtotal / unit prices / line amounts must appear verbatim, not just "reconcile" — a silently self-corrected number fails faithfulness even if internally consistent), and field-confidence checks (`verify_field_confidence`, Azure OCR confidence < 60% → `low_confidence_field` alert).

### 5. Routing the result
`route_after_verification()` decides: retry `extract` (feedback-driven, up to 2 attempts) if a genuinely fixable alert exists, or finalize as `COMPLETED` / `AUDIT_REQUIRED`. `low_confidence_field` and `extraction_failed` are deliberately excluded from the retry trigger — re-running extraction on the same OCR text won't fix an OCR-level confidence problem.

### 6. Trainer rules feed extraction (two-stage)
Before the vendor is known, `_get_template_rules()` applies the tenant's Global `ExtractionTemplate` (vendor-agnostic constraints). Once `extract_node` returns a `vendor_name`, a second pass merges in that vendor's own template (vendor wins on conflict) and re-runs extraction if a vendor template exists. This is how a Trainer-committed rule like "sum CGST+SGST into tax_amount" actually changes what gets extracted.

### 7. Persisting the result
Back in `handlers.py`, the `Invoice` row is updated with every extracted field, `status`, `sa_alerts`, and — as of the dashboard fix in this session — `completed_at` (real wall-clock finish time, used for `average_processing_time`). Progress is pushed live to the browser via `_publish_sse_events()` → Redis pub/sub → the FE's SSE subscription, so the Ingestion screen shows real `PROCESSING_OCR → EXTRACTING_DATA → INDEXING → COMPLETED/AUDIT_REQUIRED` transitions.

### 8. RAG indexing
If `status == "COMPLETED"`, `chroma_client.index_invoice_document()` chunks and embeds the document into ChromaDB, scoped by `tenant_id`, so it becomes answerable from Chat.

### 9. Chat
A user asks a question. `agents/query_agent.py::run_query_agent()`:
- `classify_query()` routes to **SQL** (any structured-field lookup — vendor, dates, totals, status), **RAG** (semantic content search over indexed chunks, with hybrid keyword-boosted reranking and a 0.4 distance relevance threshold), or **CHAT** (casual).
- SQL generation runs through a bounded 3-attempt self-repair loop, a hardened tenant-isolation regex validation, and a schema prompt that explicitly forbids hallucinating non-existent columns like `audit_flags`.
- Both SQL and RAG answer-synthesis prompts get the tenant's committed Trainer rules injected (Global always; vendor-specific ones when the question names a known vendor) — so "how is tax calculated on this invoice" answers consistently with how it was actually extracted.
- Repeated questions are served from a Redis answer cache (1hr TTL), invalidated on any Trainer commit/rollback.

### 10. Auditor
For `AUDIT_REQUIRED` invoices, `routers/audit.py::resolve_alert()` lets a user dismiss alerts and/or submit field corrections. Corrections are persisted with a before/after diff logged to `AuditLog`. If the same field gets corrected ≥3 times (same vendor, or across vendors for a global pattern), the response includes a `suggested_rule` that deep-links straight into the Trainer sandbox, pre-scoped.

### 11. Trainer
`routers/trainer.py` manages 3 rule scopes against the `ExtractionTemplate`/`ExtractionTemplateVersion` tables: **Global** (tenant-wide), **Existing Vendor** (seeded from that vendor's real production data), and **New Vendor** (blank sandbox). Sessions live in Redis (TTL-bound). Committing a rule triggers a `reaudit_templates` background re-run of matching invoices (Global → all vendors; vendor scope → that vendor only; skips anything already `PAID`/`REJECTED`), and bumps a version row for history/rollback.

### 12. Dashboard
`routers/dashboard.py::get_dashboard_metrics()` aggregates totals, spend-over-time, top vendors, and status counts from the tenant's `Invoice` rows. `extraction_accuracy` is a real alert-free rate; `average_processing_time` is now a real `completed_at - created_at` average (previously a synthetic formula — fixed this session).

---

## Part 2 — What Service Flow adds [PLANNED]

Same journey, opposite direction: instead of the tenant *receiving* invoices from their vendors, the tenant *sends* invoices to their own customers. All 11 feature docs are now written and cross-referenced below; this section reflects the final, locked design — not an earlier draft.

### 1. It arrives — Send Invoices (upload-only, not creation)
No in-app invoice creation or generation — that was considered and explicitly rejected, since it drags in logo upload, layout/template picking, and a branding settings screen that don't exist today. Instead: the tenant uploads their own **already-made** PDF (created in whatever tool they already use), which then runs through verification before it can be sent. Deferred to its own future feature: [feature_17_invoice_builder.md](apps/invoice-be/docs/feature_17_invoice_builder.md).

### 2. A parallel pipeline, not a shared one
`agents/outbound_extraction_agent.py` [PLANNED] — a wholly new module, not an edit to `extraction_agent.py`. This was a deliberate design fork: reusing the existing `InvoiceExtractionSchema` would need a new `customer_name` field added to shipped code; true zero-touch means a separate schema/prompt instead. It **does** reuse, by import only: `handlers.py::_run_ocr()` for OCR, and every pure `verify_*` function in `utils/verification_tools.py` for math/faithfulness checks. Simpler than the inbound graph — one extract→verify pass, no classify/dynamic-QA split, since a tenant's own invoice format doesn't vary the way unpredictable vendor formats do.

### 3. Standing rules — Trainer's lightweight cousin, not a Trainer scope
Full 3-scope Trainer (Global/Existing Vendor/New Vendor) doesn't fit here — there's no vendor variability to justify Existing/New Vendor scopes. But the tenant's one fixed format can still have a systematic misread, so `ExtractionTemplate` gets an additive `flow_direction` column: an `OUTBOUND` row is Global-only (`vendor_name IS NULL`), created not through Trainer's sandbox but through one checkbox in the outbound Auditor — *"Apply this as a standing rule for all future outbound invoices?"* — no chat-based refinement, no re-audit fan-out, no "try before commit" ceremony, because there's nothing to test the rule against.

### 4. Routing and status
`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED / NEEDS_REVIEW → (tenant confirms) → SENT → PAID / OVERDUE`. `OVERDUE` is computed at read-time (`SENT` + `due_date < today`), not persisted — a deliberate v1 cut to avoid standing up new scheduler infrastructure.

### 5. Auditor — pre-send validation, correction only, no Trainer suggestion
`routers/outbound_audit.py` [PLANNED] handles `NEEDS_REVIEW` invoices — missing fields, math/faithfulness alerts, duplicate invoice numbers (scoped per `customer_name`). Deliberately **does not** replicate Gap 27's "suggested_rule → Trainer deep-link" behavior: there's no vendor-scoped Trainer target for outbound to suggest into. Correction capture (Gap 26's equivalent) is mirrored; the Trainer-suggestion half isn't.

### 6. Dashboard — the one screen that splits, not tabs
`routers/outbound_dashboard.py` [PLANNED] mirrors the AP metrics shape for AR (amount collected, outstanding/at-risk receivables, top customers, real `average_days_to_payment` via new `sent_at`/`paid_at` columns). Screen behavior differs deliberately from Ingestion/Auditor: when both services are active, Dashboard shows **both halves simultaneously, side by side** — Dashboard is a passive overview where a tenant running both services wants to see totality at a glance, whereas Ingestion/Auditor are action screens (uploading one invoice, resolving one alert at a time) where a tab to pick which queue you're in is more natural. No combined/net figure appears on Dashboard anywhere — that stays Chat-only.

### 7. Chat — the one narrow, sanctioned edit to shipped code
`agents/query_agent.py` gains: `flow_direction`/`customer_name`/`customer_id` added to its SQL-generation schema description, one example SQL pattern for combined/net questions (conditional aggregation in a single query — no structural change to the existing single-query architecture, isolation regex, or retry loop), and `_get_global_business_rules()` extended to also fetch the outbound Global standing-rule template. This is the sole exception to "new files only" in the entire Service Flow effort — a fully separate Vendor Chat was considered and rejected, since it would forfeit combined/net questions and split one smart screen into two duller ones.

### 8. Trainer — genuinely unaffected
No changes. The outbound standing-rule mechanism (step 3) deliberately lives in the new outbound Auditor, not in `routers/trainer.py` or `ScopeSelector.tsx` — zero touch confirmed.

### 9. Settings — the first time this screen exists
`routers/settings.py` [PLANNED], new `Tenant.receive_invoices_enabled`/`send_invoices_enabled` columns (Admin-only, defaults preserve every existing tenant's current behavior exactly). This also became the natural home to formally establish "Settings" as a feature for the first time — Connectors/Email Ingestion/Webhooks (all still unbuilt on the FE) are consolidated here by reference, not rewritten.

### 10. Still open, deliberately not decided
Whether outbound invoices are actually delivered to a customer (email, download link, portal) — undecided, out of scope. Pricing tier — flagged as an explicit open decision with three options and no default, see [feature_3.1_vendor_flow_pricing.md](apps/invoice-website/website_features/feature_3.1_vendor_flow_pricing.md).

---

## Part 3 — File touch map (final, matches the 11 written feature docs)

| File | Status | Change |
|---|---|---|
| `models.py` (`Invoice`) | existing, edited | Additive: `flow_direction`, `customer_name`, `customer_id`, `sent_at`, `paid_at` |
| `models.py` (`ExtractionTemplate`) | existing, edited | Additive: `flow_direction` |
| `models.py` (`Tenant`) | existing, edited | Additive: `receive_invoices_enabled`, `send_invoices_enabled` |
| new Alembic migration(s) | new | All columns above, nullable/defaulted — no data migration, no existing row affected |
| `agents/outbound_extraction_agent.py` | new | Own schema/prompt/graph; imports `_run_ocr()` + `verification_tools.py` |
| `queue_worker/outbound_handlers.py` | new | `handle_process_outbound_invoice()` |
| `queue_worker/main_worker.py` | existing, edited (small) | One new `elif` branch to dispatch outbound messages |
| `agents/query_agent.py` | existing, edited (narrow) | The one sanctioned exception — see Part 2 §7 |
| `routers/outbound_invoices.py`, `routers/outbound_audit.py`, `routers/outbound_dashboard.py`, `routers/settings.py` | new | Zero edits to `routers/invoices.py`, `audit.py`, `dashboard.py` |
| FE: `SendInvoiceStatusTable.tsx`, `OutboundAlertConsole.tsx`, `OutboundMetricsGrid.tsx`, `VendorFlowToggles.tsx`, `app/settings/page.tsx` | new | New components; `DropZone.tsx`/`PdfViewerCanvas.tsx`/`ClientPerformanceChart.tsx` reused unmodified by import |
| `app/ingestion/page.tsx`, `app/dashboard/page.tsx` | existing, edited (small) | Conditional tab header / split-layout wrapper, gated on the new Settings toggles |

Full detail for every row: `apps/invoice-be/docs/feature_2.1/6.1/7.1/8.1/16/17_*.md`, `apps/invoice-fe/docs/feature_2.1/3.1/4.1/10_*.md`, `apps/invoice-website/website_features/feature_3.1_vendor_flow_pricing.md`.
