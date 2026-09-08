# System Journey — Developer Guide

Purpose: a single narrative walkthrough of how a document actually moves through this codebase, module by module — not a replacement for `Technical_Architecture_Document.md` or the per-feature `feature_N_*.md` specs (which remain the source of truth for exact task numbers and status).

**Last reconciled 2026-09-07 against trackers + code.** Every module, table, flag and endpoint named below was opened or grepped on that date; where a tracker row and the code disagreed, the code won and the disagreement is called out inline. Uncommitted Feature 29 phase-2 work in the working tree (entity resolver, semantic views, certified examples, knowledge collection) is **not** described as shipped anywhere here.

Marking convention used throughout:
- **[LIVE]** — exists, running, verified in this repo today.
- **[PARTIAL]** — code has landed and is unit-verified against real Postgres, but the tracker keeps the row `[~]` because the Azure-path manual verification has not been run.
- **[FLAG-OFF]** — code is present but gated by a `config.py` flag whose default is `False` (the dev value is stated where it differs).
- **[PLANNED]** — spec only, not built.

---

## Part 1 — The journey of an inbound document today [LIVE]

### 1. It arrives — one of many doors
A user uploads a file on the Ingestion screen (`/ingestion`). `routers/invoices.py`'s upload endpoint first hands the bytes to `services/file_intake.py::normalize_upload()` — a PDF passes through, a PNG/JPG/TIFF/WEBP/BMP is converted to PDF **once, here** (Feature 28 [PARTIAL], no flag, 50-megapixel decompression guard). It then computes a SHA-256 `file_hash` for Layer-1 duplicate detection (a hit creates a row with `status="DUPLICATE"` and `duplicate_of_invoice_id`, nothing is queued), streams the PDF to Azure Blob Storage (`services/storage.py`), creates an `Invoice` row (`status="PROCESSING"`, `batch_id`), writes one `ingestion_batches` row via `services/ingestion_batches.py::record_ingestion_batch(trigger="manual")` (Gap 464), and pushes one `process_invoice` message onto the Azure Storage Queue `extraction-tasks-queue`. The user never talks to the extraction pipeline directly — everything past this point is asynchronous.

The same shape is reused by every other door, each of which converges on the same queue message:
- **Directory watcher** — `POST /invoices/watcher/start`.
- **Google Drive connector** — `POST /connectors/import/{provider}` → worker `handle_import_connector_file` → `_enqueue_process_invoice` (`trigger="connector"`). Salesforce was removed 2026-08-28 (Gap 334); `routers/connectors.py` knows only Google Drive.
- **Autopilot** — `services/autopilot_sync.py::run_sync()` (manual `POST /autopilot/sync`, or `scripts/autopilot_job.py` for all due tenants) scans the mapped Drive folder, dedups on Drive file id and hash, and writes `tenant_autopilot_logs`; the History screen merges those rows in as `trigger: "autopilot"`. No ACA Job for the script exists in `infra/08-apps.bicep` as of 2026-09-07 — its schedule on dev is unverified.
- **Email-in** (Feature 14) — SendGrid Inbound Parse → website relay → `POST /email/mailintegration` (shared secret, fail-closed, `services/inbound_mail_security.py`) → sender allow-list (`tenant_email_senders`) → same path (`trigger="email"`); rejects land in `dropped_inbound_emails`.
- **REST API** — any of the above with an `inv_live_` tenant API key instead of a Clerk session (Feature 25, Gaps 358/359).
- **Outbound upload** — `routers/outbound_invoices.py` → `process_outbound_invoice` message (Part 2).

`GET /ingestion-history` (`routers/ingestion_history.py`) reads all of it back as one durable run log with archive/unarchive; the FE screen is `/history` (added 2026-09-05).

### 2. A worker picks it up
`queue_worker/main_worker.py` polls `extraction-tasks-queue` in a loop, dispatching messages by `task` name to a thread pool: `process_invoice`, `process_outbound_invoice`, `import_connector_file`, `reaudit_templates`, `deliver_webhook`, `process_chat_job`, `extract_attachment`. Per-tenant fair-share throttling (`_acquire_tenant_slot`/`_release_tenant_slot`, Redis-backed) stops one tenant's batch upload from starving every other tenant's queue. A message that fails `MAX_DEQUEUE_ATTEMPTS = 5` times is moved to `extraction-tasks-deadletter-queue` (a KQL alert watches it). `handle_process_invoice()` in `queue_worker/handlers.py` is the actual entry point for one inbound document.

### 3. OCR
`handlers.py::_run_ocr()` calls Azure Document Intelligence's `prebuilt-invoice` model (`DOC_INTEL_MODEL_ID`; local `pypdf` text extraction in the Ollama/dev provider). Transient connection errors get a bounded retry with exponential backoff, rotating across the configured Doc Intelligence resources on each retry. The result includes raw text, per-field OCR confidence scores, and bounding-box coordinates for the PDF viewer overlay. Progress is published as `PROCESSING_OCR`.

### 4. The extraction agent graph — **NOVA**
`agents/extraction_agent.py` compiles **one** LangGraph state machine (`_build_extraction_graph`) — since Gap 283 (2026-08-21) the outbound path uses this same graph parameterised by `flow_direction`, there is no second graph:
- `classify_doc_type_node` — **new stage** (Feature 27). `services/document_type_classifier.py` assigns one of the 14 `DOC_TYPES` (`QUOTATION, PROFORMA_INVOICE, PURCHASE_ORDER, ORDER_CONFIRMATION, CONTRACT, DELIVERY_NOTE, GRN, INVOICE, RECEIPT, CREDIT_NOTE, DEBIT_NOTE, REMITTANCE_ADVICE, STATEMENT_OF_ACCOUNT, OTHER`) with `doc_type_evidence`, and `resolve_extraction_profile(flow_direction, doc_type)` picks the schema, prompt and verification rubric for it. The node exists in the compiled graph only when `ENABLE_GENERIC_EXTRACTION` is on — it is **pinned `True` in `config.py` and must not be disabled**: off, every PO and quotation is silently graded as an invoice again.
- `classify_node` — STANDARD vs COMPLEX, via `services/invoice_classifier.py` (keyword/field-presence heuristics).
- `dynamic_qa_node` — COMPLEX documents only. A pre-analysis LLM pass asking document-specific questions (multi-rate tax, holdbacks, e-invoicing identifiers) before the main extraction call, to ground it.
- `extract_node` — the multimodal call on the **`primary` model role** (`utils/llm.get_llm(max_tokens=profile.max_tokens)`; `gpt-5.6-luna` on dev, `gpt-5-mini` in defaults/prod — see step 13), given OCR text + page images + any Trainer-taught rules (step 6). `utils/token_management.py::check_token_guardrails` refuses over-budget prompts with a `token_limit_exceeded` alert before any call.
- `verify_node` — the critic. Runs math checks (`utils/verification_tools.py::verify_totals_math`, `verify_line_items_math`), faithfulness checks against the raw OCR text (`verify_grand_total_in_source_text`, `verify_line_item_amounts_in_source_text` — a silently self-corrected number fails faithfulness even if internally consistent), and field-confidence checks (Azure OCR confidence below threshold → `low_confidence_field` alert). Alert types are registered in `utils/alert_registry.py`.

### 5. Routing the result
`route_after_verification()` decides: loop back to `extract` (feedback-driven, up to 2 attempts) if at least one alert is outside `NON_RETRYABLE_ALERT_TYPES`, otherwise end. `low_confidence_field` and `extraction_failed` are deliberately excluded from the retry trigger — re-running extraction on the same OCR text won't fix an OCR-level confidence problem. Back in `handlers.py`, the `doc_type` decides **where** the result lands (`_routes_to_documents_table`): the money family (`INVOICE`, `PROFORMA_INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE`) updates the `Invoice` row to `COMPLETED` / `AUDIT_REQUIRED`; any other known type is written to the `documents` table by `_persist_non_invoice_document` and the provisional `Invoice` row is removed, so the ledger, dashboard and audit queue never see it. `GET/DELETE /documents` (`routers/documents.py`) read and soft-delete those rows; the delete also drops the document's Chroma chunks (`delete_document_chunks`, Feature 27 R6 / Gaps 397-399, 460).

### 6. Trainer rules feed extraction (two-stage)
Before the vendor is known, `_get_template_rules()` applies the tenant's Global `ExtractionTemplate` (vendor-agnostic constraints). Once `extract_node` returns a `vendor_name`, a second pass merges in that vendor's own template (vendor wins on conflict) and re-runs extraction if a vendor template exists. This is how a Trainer-committed rule like "sum CGST+SGST into tax_amount" actually changes what gets extracted.

### 7. Persisting the result
Back in `handlers.py`, the `Invoice` row is updated with every extracted field, `status`, `sa_alerts`, `doc_type`, `doc_attributes` (`services/doc_attributes.py`) and `completed_at` (real wall-clock finish time, used for `average_processing_time`). Progress is pushed live to the browser via `_publish_sse_events()` → Redis channel `invoice.update.{batch_id}` → `GET /invoices/stream/{batch_id}` → the FE's `EventSource`, so the Ingestion screen shows real `PROCESSING_OCR → EXTRACTING_DATA → INDEXING → COMPLETED/AUDIT_REQUIRED/FAILED` transitions. On `COMPLETED` / `AUDIT_REQUIRED` a `deliver_webhook` message is queued for every matching subscription (`invoice.completed` / `invoice.audit_required`, Feature 15, HMAC-signed with retry and auto-disable). Rows stuck in `PROCESSING` are re-enqueued by `services/invoice_reconciliation.py` (`scripts/reconcile_stuck_invoices.py`).

### 8. RAG indexing
If `should_index_status(status)` passes, `chroma_client.index_invoice_document()` opens the PDF with PyMuPDF, makes **one chunk per page** prefixed with a `[Vendor | Document ID | Page]` header, embeds with the local `BAAI/bge-m3` model and writes into the **per-tenant** collection `invoice_chunks_{tenant_id}` (metadata `tenant_id`, `invoice_id`, `vendor_name`, `page`). Non-invoice documents go the same way into `docs_{tenant_id}` via `index_document_chunks()` (no `invoice_id`, carries `document_id` + `doc_type`). There is no shared collection filtered by tenant metadata — the collection name is the isolation boundary.

### 9. Chat — **SAGE**
A user asks a question. `POST /chat/sessions/{id}/message` (`routers/chat.py`) no longer runs the agent inline: `ENABLE_ASYNC_CHAT_QUEUE` defaults **True** (Gap 280 — a few `routers/chat.py` docstrings still say False; the code is what counts), so `services/chat_queue.py` pushes a job onto Redis list `chat_tasks_queue` (per-tenant ceiling `chat_inflight:{tenant}` = 3, HTTP 429 + `Retry-After` beyond it, Gap 364) and returns a `job_id`; the browser follows `GET /chat/jobs/{job_id}/stream` (SSE) or `/status`. The worker's `handle_process_chat_job` takes a per-session Redis lock and runs `agents/query_agent.py::run_query_agent()`:
- `classify_query()` — on the **`fast` model role** (Feature 6.1 A2) — routes to **SQL** (any structured-field lookup — vendor, dates, totals, status, both directions), **RAG** (semantic content search over indexed chunks, hybrid keyword-boosted, 0.49 distance cutoff re-derived in Gap 244), **CHAT** (casual), or the **attached-document branch** when the session holds Feature 26 attachments (step 10).
- SQL generation gets a schema-linking block first (`_schema_linking_block_for`, Feature 6.1 C4), keeps a stable cacheable prompt prefix for Azure prompt caching (A4), honours `AZURE_OPENAI_SQL_REASONING_EFFORT` (A1), runs a bounded 3-attempt self-repair loop, and is only executed after **`assert_tenant_isolation_on_ast()` proves the `tenant_id` predicate on the `sqlglot` parse tree** (Gap 414 — the old regex is gone). Zero rows are diagnosed (`_diagnose_zero_rows`, `_zero_rows_clarification`, Gap 424) rather than answered as "none".
- Every answer route then attaches the **full invoice record(s)** it is about (`services/full_records.py`, Feature 29 §29.5 — `items`, `taxes`, `sa_alerts`, `notes`, chunks), computes figures in Python (`_computed_figures_block_for`, `services/document_comparison.check_line_arithmetic`, §29.6), and phrases the answer (full-record narration on the `chat_summary` role). `ENABLE_CHAT_STREAMING` (A3) streams those phrasing calls — **[FLAG-OFF]** by default, `true` on dev.
- Both SQL and RAG synthesis prompts get the tenant's committed Trainer rules injected (Global always; vendor-specific ones when the question names a known vendor), plus Feature 18 chat-correction rules from `tenant_chat_rules` (`_chat_rules_block`) and the tenant's chat style.
- `_answer_contract_gate()` (Feature 29 §29.9, `ENABLE_ANSWER_CONTRACT_GATE` default True) rejects prose containing a figure that is not in the evidence — one named-figure regeneration, then an abstain payload.
- Repeated questions are served from the Redis answer cache `chat_answer_cache:{tenant}:{normalized question}` (1 h TTL, keyed on the sorted attachment ids too, §29.12), **skipped for narrowing follow-ups so one session's answer never leaks into another** (Gap 423), and invalidated on any Trainer commit/rollback. Memory is the `chatmessage` transcript plus `chatsession.history_summary` / `focus`; there is no LangGraph checkpointer and no `chat_qa_shortcuts` table.
- If `ENABLE_PRODUCTION_QUALITY_JUDGE` is on (**[FLAG-OFF]** by default, `true` on dev) `services/online_quality_judge.py` grades the real turn afterwards (Feature 23) and `telemetry.py` emits `chat_turn` / `llm_agent_call` events for every call.

### 10. Chat with a document you are holding — Feature 26 [LIVE; content chat FLAG-OFF]
`POST /chat/sessions/{id}/attachments` (`routers/chat_attachments.py`) stores a PO / quotation / delivery note / other document as a `chat_attachments` row (no `Invoice` row, no billing counter) and queues `extract_attachment`. The worker (`handle_extract_attachment` → `services/attachment_extraction.py`) runs `_run_ocr` + the same extraction graph — so the Feature 27 classifier supplies its `doc_type` (Gap 430) — indexes its pages into `chat_docs_{tenant_id}` (`services/chat_document_search.py`) and matches it to invoices with `services/document_comparison.find_candidate_invoices()`: Tier 1 exact PO number, Tier 2 party name + date window, Tier 3 extended candidates; anything ambiguous comes back as a confirmation card the user answers through `POST /chat/attachments/{id}/confirm-matches`. The next turn's `_run_attached_document_turn` / `_compare_attachment_to_invoices` produce a **deterministic** header + line diff in the mode that fits the attachment's type (`resolve_comparison_mode`: quantity mode for delivery notes, list-reconcile for statements, …), stored in `document_comparisons` with tolerances from `match_policies`, plus suggested actions. Questions about the attachment's own text are behind `ENABLE_GENERIC_DOC_CHAT` (**[FLAG-OFF]** default False, `true` on dev). Attachments expire after `CHAT_ATTACHMENT_TTL_DAYS` = 30 (`scripts/sweep_chat_attachments.py`, ACA job `caj-chat-doc-ttl`), which also deletes their chunks.

### 11. Auditor — **SENTINEL**
For `AUDIT_REQUIRED` invoices, `routers/audit.py::resolve_alert()` (`PUT /audit/resolve/{invoice_id}`) lets a user dismiss alerts and/or submit field corrections. Corrections are persisted with a before/after diff logged to `audit_logs`. If the same field gets corrected ≥3 times (same vendor, or across vendors for a global pattern), the response includes a `suggested_rule` that deep-links straight into the Trainer, pre-scoped. The route is guarded by `require_actions_scope`, so a human needs `can_audit` and an API key needs `api_key_scope = "actions"` (Feature 25); resolving fires `invoice.approved` / `invoice.rejected` webhooks.

### 12. Trainer — **EVOLVE** (alert-anchored, Feature 18)
`routers/trainer.py` + `services/trainer_sessions.py` (Redis `trainer:session:*`, TTL-bound) run the sandbox against the `extraction_templates` / `extraction_template_versions` tables. A session opens on a real document — `POST /trainer/upload` (transient, never written to `invoice`) or `POST /trainer/sessions/from-invoice` (an already-processed invoice, no OCR re-run, anchored on its stored `sa_alerts`). The former free-text **Global** session (`/sessions/global`) and the "latest invoice of this vendor" entry (`/sessions/from-production`) now return **410 Gone** — Global template rows and every read of them remain, but new Global rules are no longer typed in prose. Corrections (`corrections/{tolerance,confidence-threshold,alert-override,missed-alert}`, `chat`) refine constraints via `agents/trainer_agent.py`; `preview` replays the candidate rule over history (`services/rule_impact.py`) before anything is persisted. `commit` bumps a version row, queues `reaudit_templates` (re-runs matching `COMPLETED`/`AUDIT_REQUIRED` invoices — Global → all vendors; vendor scope → that vendor only) and invalidates the chat answer cache; `templates/history` and `templates/{id}/rollback/{version}` give history/rollback. Chat-side corrections (`/chat/rules/*`, table `tenant_chat_rules`) are the same feature's other half. *Tracker note: the BE tracker row still reads "Feature 18 CANCELLED 2026-08-20"; the modules above are present and imported, so it is [LIVE] here.*

### 13. Which model answers — the model layer (Feature 29, Gaps 465/466)
Nothing above names a model directly. `utils/model_registry.py` defines four **roles** — `primary`, `fast`, `judge`, `chat_summary` — and `utils/llm.py` (`get_llm`, `get_llm_for_role`, `get_chat_summary_llm`) resolves each to the Azure OpenAI deployment named in `config.py` (`AZURE_OPENAI_DEPLOYMENT_NAME`, `..._FAST_...`, `..._JUDGE_...`, `..._CHAT_SUMMARY_...`, `..._LONG_DOC_...`). Dev (`infra/params.dev.json`): primary + fast = `gpt-5.6-luna`, judge + chat_summary = `gpt-5-mini`, long_doc empty (inert). Prod params: `gpt-5-mini`. Data-plane api-version is `2024-10-21` everywhere. The registry also prices every `llm_agent_call` event and supplies the context limit the token guardrail uses. `gpt-4o` deployments, `gpt-6-astra` and `gpt-5.6-sol` are gone; the Ollama provider remains for local runs only.

### 14. Dashboard
`routers/dashboard.py::get_dashboard_metrics()` aggregates totals, spend-over-time, top vendors, and status counts from the tenant's inbound `Invoice` rows (`flow_direction = 'INBOUND'`). `extraction_accuracy` is a real alert-free rate; `average_processing_time` is a real `completed_at - created_at` average. `/dashboard/insights` (+ `insights/dismiss`) and `/dashboard/trainer-impact` feed the insight cards and the EVOLVE impact tile. When `send_invoices_enabled` is on, the screen shows the AR half from `routers/outbound_dashboard.py` side by side (Part 2).

### 15. Watching it run — Features 20 / 23 [LIVE]
`telemetry.py` sends `llm_agent_call`, `chat_turn`, `agent_eval_summary`, `extraction_benchmark_run`, `azure_cost_snapshot`, `online_eval_signal` and `ops_recommendation` events plus dependency spans to Application Insights; the FE reports RUM through `components/monitoring/AppInsightsProvider.tsx`. Three Azure Workbooks (Cost + Health, AI Control Tower, Ops Summary — flat, no tabs) read them in `rg-invoice-llm-dev`. Nightly, ACA job `caj-benchmark-eval` runs `scripts/run_extraction_benchmark.py` and `scripts/run_agent_eval.py` (the LLM-judge golden bank, with `--taxonomy` failure tagging and a κ calibration gate that currently fails — Feature 29 §29.2 / Gap 479); `caj-online-signals` emits 6-hourly quality signals. The Feature 24 Ops Digest agent and the Feature 21 SAGE orchestrator were deleted on 2026-08-25 (Gaps 311/316); the `clarification_rate` / `budget_exhaustion_rate` signals they fed are permanently degenerate.

### 16. Getting help — Feature 19 [LIVE]
`/help` hosts seven guides and a support bot. `POST /support/chat` runs `agents/support_agent.py` — a deterministic keyword matcher over a curated knowledge base with a Chroma `support_knowledge_topics` vector fallback for zero-hit queries (Gap 403); **it makes no LLM call** (recorded deviation from the spec). Escalation creates a `supportticket` through `POST /support/ticket`; the public website form posts to `POST /support/contact` (rate-limited); `services/support_email.py` sends the staff alert and the submitter receipt.

---

## Part 2 — What Service Flow adds [LIVE since 2026-07-29, refactored 2026-08-21]

Same journey, opposite direction: instead of the tenant *receiving* invoices from their vendors, the tenant *sends* invoices to their own customers. Every module in this part exists and is exercised by the test suite; the tracker keeps "real end-to-end manual verification against live Azure" outstanding on Features 2.1 / 7.1 / 8.1 / 6.1.

### 1. It arrives — Send Invoices
The tenant uploads their own **already-made** PDF (or image, Feature 28) on the Ingestion screen's Send Invoices tab → `POST /outbound-invoices/upload` (`routers/outbound_invoices.py`) → `Invoice(flow_direction="OUTBOUND", status="UPLOADED")` → `process_outbound_invoice` message. Since 2026-09-04 there is also **clone-and-edit** (Feature 17 Invoice Builder [PARTIAL]): `GET /outbound-invoices/{id}/build-defaults` → `POST /build/preview` → `POST /build`, with the pure core in `services/invoice_builder.py` (`BuildRequest`, `compute_totals`, `next_invoice_number`, `default_build_from_source`, `builder_intent`) and a structured re-render in `services/pdf_render.py` (`harvest_branding`, `render_invoice`); the new row carries `source_invoice_id` + `builder_intent` and then runs through the same verification. The FE screen is `/invoices/outbound-builder` (added 2026-09-05). The "substitution" render mode and `services/pdf_substitute.py` were deleted (Gap 462) although the tracker's Feature 17 row still names the file.

### 2. One pipeline, parameterised — not a parallel one
`agents/outbound_extraction_agent.py` is a **thin wrapper** (`run_outbound_extraction_agent`) over the single graph in `extraction_agent.py`. The separate 2-node outbound graph the original design called for was built and then removed on 2026-08-21 (Gap 283) because it silently missed every inbound improvement — classify/dynamic-QA, the retry loop, the faithfulness checks. Everything outbound-specific — `OutboundInvoiceExtractionSchema`, prompts, required fields and the `VERIFIED`/`NEEDS_REVIEW` vocabulary — lives in `_DIRECTION_PROFILES["OUTBOUND"]`. `queue_worker/outbound_handlers.py::handle_process_outbound_invoice()` is the worker entry point; it applies the tenant's outbound Global standing rules (`_get_outbound_global_rules`) and indexes both `VERIFIED` and `NEEDS_REVIEW` invoices into Chroma so Chat can see them (Gap 243).

### 3. Standing rules — Trainer's lightweight cousin, not a Trainer scope
`ExtractionTemplate.flow_direction` exists: an `OUTBOUND` row is Global-only (`vendor_name IS NULL`), created not through Trainer's sandbox but from the outbound Auditor — *"Apply this as a standing rule for all future outbound invoices?"* — no chat-based refinement, no re-audit fan-out, because there is nothing to test the rule against.

### 4. Routing and status
`UPLOADED → PROCESSING_OCR → EXTRACTING_DATA → VERIFIED / NEEDS_REVIEW → (tenant confirms, PUT /{id}/confirm-send, sets sent_at) → SENT → PAID (PUT /{id}/mark-paid, sets paid_at)`. `OVERDUE` is computed at read-time (`SENT` + `due_date < today`) and never written to `status`; `scripts/sweep_outbound_overdue.py` (ACA job `caj-overdue-sweep`, not yet deployed on dev) fires `outbound_invoice.overdue` webhooks, and `outbound_invoice.sent` / `outbound_invoice.approved` fire on the transitions.

### 5. Auditor — pre-send validation, correction only, no Trainer suggestion
`routers/outbound_audit.py` (`PUT /outbound-audit/resolve/{invoice_id}`, `require_actions_scope`) handles `NEEDS_REVIEW` invoices — missing fields, math/faithfulness alerts, duplicate invoice numbers (scoped per `customer_name`). Deliberately **does not** replicate Gap 27's "suggested_rule → Trainer deep-link" behaviour: there is no vendor-scoped Trainer target for outbound to suggest into. The FE console is `/invoices/outbound-review/[id]`.

### 6. Dashboard — the one screen that splits, not tabs
`routers/outbound_dashboard.py` (`GET /outbound-dashboard/metrics`, `/invoices`) mirrors the AP metrics shape for AR (amount collected, outstanding/at-risk receivables, top customers, real `average_days_to_payment` from `sent_at`/`paid_at`, `revenue_over_time`). When both services are active, Dashboard shows **both halves simultaneously, side by side**; Ingestion/Auditor use a tab. No combined/net figure appears on Dashboard anywhere — that stays Chat-only.

### 7. Chat — the one narrow, sanctioned edit to shipped code
`agents/query_agent.py` carries `flow_direction`/`customer_name` in its SQL-generation schema, an example pattern for combined/net questions (conditional aggregation in a single query), and `_get_global_business_rules()` also fetches the outbound Global standing-rule template. Everything in Part 1 §9 (async queue, AST isolation, full records, answer contract) applies to outbound questions unchanged.

### 8. Trainer — genuinely unaffected
No changes. The outbound standing-rule mechanism (step 3) lives in the outbound Auditor, not in `routers/trainer.py`.

### 9. Settings — Feature 16 [LIVE]
`routers/settings.py` — `GET/PUT /settings/vendor-flow` toggles `Tenant.receive_invoices_enabled` / `send_invoices_enabled` (Admin-only; enabling send requires the Pro Combined plan and at least one authorised outbound sender). The same router now also owns Feature 25's surfaces: `/settings/security/api-key` (+ `rotate`, `verify`), `/settings/security/widget-tokens`, and `/settings/workflow` (`tenant_workflow_configs`: full_automation ↔ `Tenant.api_key_scope = "actions"`, strict_review ↔ `"readonly"`; CSV/JSON export via `services/invoice_export.py`, email summary and Drive archive via `services/workflow_outputs.py`). FE: `/settings/{security,workflows,…}`; the Plug & Play wizard (FE Feature 17) is [PARTIAL]; public `inv_test_` sandbox keys are [FLAG-OFF] (`SANDBOX_KEYS_ENABLED`).

### 10. Still open, deliberately not decided
Whether outbound invoices are actually delivered to a customer by the platform (email, download link, portal) — undecided, out of scope; `services/outbound_email.py` sends staff notifications only (never customers, Gap 125). Pricing is settled on the website (Pro Combined ₹8,999/mo for both directions); [feature_3.1_vendor_flow_pricing.md](../../apps/invoice-website/website_features/feature_3.1_vendor_flow_pricing.md) records how it got there.

---

## Part 3 — File touch map (what actually exists on 2026-09-07)

| File | Status | Role in the journey |
|---|---|---|
| `models.py` (`Invoice`) | [LIVE] | Both directions in one table: `flow_direction`, `customer_name`, `sent_at`, `paid_at`; `doc_type`, `doc_type_evidence`, `doc_attributes` (F27); `duplicate_of_invoice_id`; `source_invoice_id`, `builder_intent` (F17); `notes`; `deleted_at` |
| `models.py` (`Document`, table `documents`) | [LIVE] | Feature 27 non-invoice documents |
| `models.py` (`ExtractionTemplate`, `ExtractionTemplateVersion`) | [LIVE] | `flow_direction`; version rows for rollback |
| `models.py` (`Tenant`) | [LIVE] | `receive_invoices_enabled`, `send_invoices_enabled`, `api_key_hash`, `api_key_scope`, `cancel_requested_at` |
| `models.py` (`ChatAttachment`, `MatchPolicy`, `DocumentComparison`) | [LIVE] | Feature 26 |
| `models.py` (`IngestionBatch`, `TenantAutopilotLog.hidden_at`) | [LIVE] | Gap 464 history, Gap 429 hide/prune |
| `models.py` (`TenantWorkflowConfig`, `SandboxTenant`, `WidgetToken`) | [LIVE] | Feature 25 |
| `alembic/versions/*` | [LIVE] | Single head `e7f8a9b0c1d2`; add-only migrations, no backfills |
| `agents/extraction_agent.py` | [LIVE] | The one graph: `classify_doc_type → classify → dynamic_qa → extract → verify` |
| `agents/outbound_extraction_agent.py` | [LIVE] | Thin wrapper, no graph of its own (Gap 283) |
| `queue_worker/main_worker.py`, `handlers.py`, `outbound_handlers.py` | [LIVE] | Dispatch by task name; inbound/outbound/chat/attachment/webhook/re-audit handlers |
| `services/file_intake.py` | [PARTIAL] | Feature 28 image → PDF at every door |
| `services/document_type_classifier.py`, `services/doc_attributes.py` | [LIVE] | Feature 27 |
| `services/document_comparison.py`, `chat_document_search.py`, `attachment_extraction.py` | [LIVE] | Feature 26 |
| `services/full_records.py` | [LIVE] | Feature 29 §29.5 full-record chat context |
| `services/chat_queue.py` | [LIVE] | Gap 280 async chat queue (default on) |
| `services/ingestion_batches.py`, `routers/ingestion_history.py` | [PARTIAL] | Gap 464 — no live dev run recorded |
| `services/invoice_builder.py`, `services/pdf_render.py` | [PARTIAL] | Feature 17 (`pdf_substitute.py` deleted, Gap 462) |
| `agents/query_agent.py` | [LIVE] | SAGE — direction-aware SQL, RAG, attachments, full records, answer contract |
| `agents/query_tools.py`, `agents/sage_prompts.py` | [LIVE] | Feature 21 remnants still consumed by `query_agent.py` (`get_full_record`, `PERSONA_BLOCK`); `sage_orchestrator.py` deleted |
| `agents/support_agent.py` | [LIVE] | Deterministic keyword + vector matcher, no LLM |
| `agents/trainer_agent.py`, `services/trainer_sessions.py`, `services/rule_impact.py`, `services/chat_rules.py` | [LIVE] | EVOLVE + Feature 18 (tracker row says cancelled; code is live) |
| `routers/outbound_invoices.py`, `outbound_audit.py`, `outbound_dashboard.py`, `settings.py` | [LIVE] | Service Flow + Feature 16/25 settings — zero edits to `routers/invoices.py`, `audit.py`, `dashboard.py` |
| `routers/chat_attachments.py`, `documents.py`, `config_features.py`, `sandbox.py`, `widget.py` | [LIVE] | Added since 2026-08-18 |
| `utils/model_registry.py`, `utils/llm.py` | [LIVE] | Model roles; api-version `2024-10-21` |
| `services/agent_eval.py`, `online_quality_judge.py`, `online_eval_signals.py`, `ops_recommendation.py` | [LIVE] | Feature 23 judges and signals (production judge flag-off by default, on in dev) |
| `services/ops_digest*.py`, `scripts/ops_digest_job.py`, `agents/sage_orchestrator.py`, `services/pdf_substitute.py`, Salesforce connector paths | deleted | Gaps 311, 316, 462, 334 |
| FE `app/ingestion/page.tsx` (Upload / Autopilot / Send tabs), `app/history/page.tsx`, `app/invoices/page.tsx`, `app/invoices/{review,outbound-review}/[id]`, `app/invoices/outbound-builder/page.tsx`, `app/chat/page.tsx` + `components/chat/{AttachmentChip,AttachmentMatchConfirm,DocumentEvidence,ReconciliationTable}.tsx`, `app/dashboard/page.tsx` (split grid), `app/settings/{security,workflows}/page.tsx`, `lib/featureFlags.ts` | [LIVE] (`/invoices/outbound-builder`, `/settings/workflows` [PARTIAL]) | Screens for every stage above; `middleware.ts` exempts `/api/(.*)` from Clerk so API-key callers share the proxy (FE Gap 358) |
| FE `src-tauri/`, `.github/workflows/build-desktop.yml` | deleted | Desktop app (FE Feature 18) reset to a PWA plan — [PLANNED] |
| `infra/*.bicep`, `infra/*-only.bicep` | [LIVE] on dev | Container apps, ChromaDB app, Front Door custom domain, scheduled jobs (billing/overdue/sandbox sweeps not deployed on dev), workbooks, alerts. `deploy-dev.yml` never runs tests (Gap 312) |

Full detail for every row: `apps/invoice-be/docs/feature_{2,2.1,6,6.1,7,7.1,8.1,13,14,15,16,17,18,19,20_23_24,25,26,27,28,29}_*.md`, `apps/invoice-fe/docs/`, `apps/invoice-website/website_features/`, and the three trackers.
