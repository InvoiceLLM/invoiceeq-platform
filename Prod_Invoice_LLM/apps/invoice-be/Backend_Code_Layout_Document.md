# API Flow Directory & Code Mapping

This document maps each system API to its sequential file and function execution path, reconciled against the actual `apps/invoice-be` implementation. Steps marked **[Not yet implemented]** describe intended/roadmap behavior that does not exist in code yet — see the corresponding `docs/*.md` file for tracked status.

> **Last reconciled 2026-09-07 against `main.py`, `routers/`, `services/`, `agents/`, `queue_worker/`, `scripts/`, `dependencies.py`, `utils/model_registry.py` and `config.py` at commit `d9b6ce2` (HEAD).** Every endpoint, file and function named below was read from code on that date. The working tree also carries **uncommitted Feature 29 phase-2 work from a concurrent session** (new `ENABLE_ENTITY_RESOLVER` / `ENABLE_SEMANTIC_VIEWS` / `ENABLE_CERTIFIED_EXAMPLES` / `ENABLE_KNOWLEDGE_LAYER` / `ENABLE_RERANK` flags and their services) — that work is **in progress, uncommitted 2026-09-07** and is deliberately not described as live anywhere in this document.

**Router registry (`main.py` L179-207).** Every router below is mounted under `/api/v1` except `auth` (mounted bare at `/auth`). App-level routes: `GET /`, `GET /health`, `GET /health/liveness`, `GET /health/readiness` (Postgres `SELECT 1` + non-fatal Redis ping). Middleware: `TracingAndLoggingMiddleware` (`utils/logging_config.py`), `CORSMiddleware`, `WidgetCORSMiddleware` (`routers/widget.py`); `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")` when App Insights is configured (Gap 292). `routers/webhook_docs.py` is documentation-only: its 7 routes are appended to `app.webhooks.routes` for the OpenAPI "webhooks" section and are never callable (Gap 184).

| Router file | Prefix | Router-level gate | Endpoints | Flow |
| :--- | :--- | :--- | :--- | :--- |
| `routers/auth.py` | `/auth` (no `/api/v1`) | — | `GET /me`, `POST /provision`, `POST /logout` | 16 |
| `routers/invoices.py` | `/invoices` | per-endpoint | `POST /upload`, `POST /watcher/start`, `GET /stream/{batch_id}`, `GET /status/{job_id}`, `GET ""`, `GET /batches`, `DELETE /batches/{batch_id}`, `GET /{invoice_id}`, `GET /{invoice_id}/pdf`, `DELETE /{invoice_id}` | 1, 2 |
| `routers/chat.py` | `/chat` | per-endpoint | `GET/POST /sessions`, `PUT/DELETE/GET /sessions/{id}`, `POST /sessions/{id}/message`, `GET /jobs/{job_id}/status`, `GET /jobs/{job_id}/stream`, `PUT/DELETE /messages/{id}/feedback`, `POST /messages/{id}/triage`, `POST /messages/{id}/triage/source-verdict`, `GET /rules/categories`, `POST /rules/preview`, `POST /rules/commit`, `GET /rules`, `DELETE /rules/{rule_id}` | 3 |
| `routers/chat_attachments.py` **(new 2026-09-01)** | `/chat` | — | `POST /sessions/{id}/attachments`, `POST /attachments/{id}/confirm-matches`, `GET /attachments/{id}` | 8 |
| `routers/documents.py` **(new 2026-09-05)** | `/documents` | — | `GET ""`, `GET /{document_id}`, `DELETE /{document_id}` | 9 |
| `routers/ingestion_history.py` **(new 2026-09-05)** | `/ingestion-history` | — | `GET ""`, `GET /{run_id}/files`, `POST /archive-all`, `POST /{run_id}/archive`, `POST /{run_id}/unarchive` | 10 |
| `routers/config_features.py` **(new)** | `/config` | — | `GET /features` | 11 |
| `routers/audit.py` | `/audit` | `require_actions_scope` | `PUT /resolve/{invoice_id}` | 4 |
| `routers/dashboard.py` | `/dashboard` | — | `GET /metrics`, `GET /trainer-impact`, `GET /insights`, `POST /insights/dismiss` | 5 |
| `routers/connectors.py` | `/connectors` | — | `GET /status`, `GET /auth-url/{provider}`, `GET /callback/{provider}`, `GET /files/{provider}`, `POST /import/{provider}`, `DELETE /{provider}` | 7 |
| `routers/trainer.py` | `/trainer` | `require_can_train` | `POST /upload`, `GET /sessions/{id}/pdf`, `POST /sessions/global` (410), `POST /sessions/from-production` (410), `POST /sessions/from-invoice`, `GET /alert-types`, `GET /vendors`, `GET /chat-style`, `POST /sessions/{id}/commit-behavior`, `PUT /sessions/{id}/mode`, `POST /sessions/{id}/corrections/{tolerance\|confidence-threshold\|alert-override\|missed-alert}`, `POST /sessions/{id}/preview`, `POST /sessions/{id}/chat`, `POST /sessions/{id}/commit`, `GET /templates/history`, `POST /templates/{id}/rollback/{version}` | 6 |
| `routers/settings.py` | `/settings` | per-endpoint | `GET/PUT /vendor-flow`, `GET /security/api-key`, `POST /security/api-key/rotate`, `GET /security/api-key/verify`, `GET/PUT /workflow`, `GET/POST /security/widget-tokens`, `DELETE /security/widget-tokens/{id}` | 12 |
| `routers/email_ingestion.py` | `/email` | — | `GET /settings/mailbox`, `GET/POST /settings/email-senders`, `DELETE /settings/email-senders/{id}`, `POST /mailintegration` (public, shared secret) | 13 |
| `routers/outbound_invoices.py` | `/outbound-invoices` | per-endpoint | `POST /upload`, `GET /{id}/build-defaults`, `POST /build/preview`, `POST /build`, `PUT /{id}/confirm-send`, `PUT /{id}/mark-paid` | 14 |
| `routers/outbound_audit.py` | `/outbound-audit` | `require_actions_scope` | `PUT /resolve/{invoice_id}` | 4 |
| `routers/outbound_dashboard.py` | `/outbound-dashboard` | — | `GET /invoices`, `GET /metrics` | 5 |
| `routers/webhooks.py` | `/webhooks` | — | `GET ""`, `POST ""`, `PUT /{id}`, `GET /{id}/deliveries`, `DELETE /{id}` | 15 |
| `routers/billing.py` | `/billing` | `get_tenant_context_allow_unpaid` | `GET /usage`, `POST /cancel`, `POST /reactivate`, `POST /create-checkout-session`, `POST /payu/success`, `POST /payu/failure` | 17 |
| `routers/admin.py` | `/admin` | `require_admin` | `GET /users`, `PUT /users/{user_ref}/permissions`, `DELETE /users/{user_ref}`, `GET /dropped-emails` | 18 |
| `routers/autopilot.py` | `/autopilot` | — | `GET/PUT /config`, `POST /sync`, `GET /history`, `GET /history/legacy/files`, `GET /history/{batch_id}/files`, `DELETE /history`, `DELETE /history/{batch_id}` | 19 |
| `routers/support.py` | none (paths carry `/support/…`) | per-endpoint | `POST /support/chat`, `POST /support/contact` (public), `POST /support/ticket`, `GET /support/tickets` | 20 |
| `routers/sandbox.py` **(new 2026-08-30)** | `/sandbox` | 404 unless `SANDBOX_KEYS_ENABLED` | `POST /keys` (public), `GET /keys/me`, `POST /claim` | 21 |
| `routers/widget.py` **(new 2026-08-30)** | `/widget` | `get_widget_context` (token, not JWT) | `POST /chat/message` | 22 |

Auth gates live in `dependencies.py`: `get_tenant_context()` (Clerk JWT or `inv_live_`/`inv_test_` API key via `get_tenant_or_api_key_context()` → `resolve_api_key_context()`), `get_tenant_context_allow_unpaid()`, `require_permission("can_train" | "can_audit" | "can_load" | "can_send_invoices")` → `require_can_train` etc., `require_key_scope(KEY_SCOPE_ACTIONS)` → `require_actions_scope`, `require_permission_or_api_key("can_load")` → `require_can_load_or_api_key`, `require_admin`, and `WidgetContext` for widget tokens.

---

## Flow 1: Ingest & Extract Invoice (Async Pipeline)
* **API Endpoints**: `POST /api/v1/invoices/upload` (Upload) & `GET /api/v1/invoices/stream/{batch_id}` (SSE status stream)

```
1. API Router
   └─ File: routers/invoices.py -> Function: upload_invoices() -> _ingest_single_file() per file
      - services/file_intake.py -> normalize_upload() / sniff_format() / convert_image_to_pdf(): Feature 28 —
        PNG/JPG/TIFF/WEBP/BMP are converted to PDF once, at the door
      - Computes SHA-256 file hash and short-circuits to a DUPLICATE record (duplicate_of_invoice_id set, Gap 195)
        if a match exists for the tenant (Layer 1 dedup)
      - services/billing_quota.py -> count_billable_uploads() / charge_free_quota() (row-locked free-tier charge)
      - services/ingestion_batches.py -> record_ingestion_batch(trigger="manual") — Gap 464 run ledger
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context() (Clerk JWT or inv_live_/inv_test_ API key);
      upload is gated by require_can_load_or_api_key
3. Storage & DB write
   └─ File: services/storage.py -> Function: upload_pdf_to_blob_storage(file_bytes, tenant_id, invoice_id)
      (called via run_in_threadpool with the callable — the 2026-07 return-value bug is fixed)
   └─ Invoice row written with status PROCESSING, batch_id, file_hash, submitted_by_email, last_enqueued_at
4. Async Task Queue (Azure Storage Queue `extraction-tasks-queue`, message {"task": "process_invoice", "kwargs": …})
   └─ File: queue_worker/main_worker.py -> Function: poll_queue() -> _process_message()
      - MAX_WORKERS = 10 threads; per-tenant fair share PER_TENANT_MAX_INFLIGHT = 3 via Redis `inflight:{tenant}`
        (_acquire_tenant_slot / _release_tenant_slot, Gap 42)
      - MAX_DEQUEUE_ATTEMPTS = 5, then _route_to_dead_letter_queue() -> `extraction-tasks-deadletter-queue`
   └─ File: queue_worker/handlers.py -> Function: handle_process_invoice(batch_id, file_path, tenant_id)
5. OCR / Layout Extraction
   └─ File: queue_worker/handlers.py -> Function: _run_ocr(file_path, settings)
      - utils/doc_intel_client.py -> get_doc_intel_pool() -> begin_analyze_document() with
        settings.DOC_INTEL_MODEL_ID (default `prebuilt-invoice`, 1-3 pooled Document Intelligence accounts)
6. Multi-Modal Extraction & Verification (LangGraph, 5 nodes, compiled once per flag state)
   └─ File: agents/extraction_agent.py -> Function: run_extraction_agent() -> _compiled_extraction_graph()
      - classify_doc_type_node(): Feature 27 — services/document_type_classifier.py::classify_doc_type()
        (deterministic first, LLM fallback; 14 DOC_TYPES) — always in the graph since Gap 461 pinned
        ENABLE_GENERIC_EXTRACTION=True
      - classify_node() -> dynamic_qa_node() -> extract_node() (structured LLM extraction over OCR text +
        base64 page images; direction profiles INBOUND / OUTBOUND / REFERENCE / GENERIC select the prompt
        builder and schema) -> verify_node() (utils/verification_tools.py arithmetic checks)
      - add_conditional_edges("verify", route_after_verification, {"extract": retry, END}) — the
        self-correction loop back to extract_node exists
   └─ Non-invoice result (E10): handlers.py writes a `documents` row (services/doc_attributes.py fills
      doc_attributes), deletes the placeholder Invoice row in the same transaction, and indexes into
      chroma_client.index_document_chunks() -> `docs_{tenant_id}`
7. Template Rule Lookup (not an agent tool — happens in the worker before extraction)
   └─ File: queue_worker/handlers.py -> queries ExtractionTemplate (tenant Global row + per-vendor row,
      flow_direction-aware), falls back to config/default_templates.json
8. Vector Indexing (runs when chroma_client.should_index_status(status) — every status outside
   NON_INDEXABLE_STATUSES, so AUDIT_REQUIRED invoices are indexed too; Gaps 240/243)
   └─ File: chroma_client.py -> Function: index_invoice_document() -> get_embeddings() -> `invoice_chunks_{tenant_id}`
9. Fan-out after the terminal status
   └─ services/webhooks.py -> dispatch_webhook_event() (invoice.processing / invoice.completed / invoice.audit_required …)
   └─ services/staff_notify.py -> notify_processing_complete() (SendGrid, staff only — never end customers)
10. Real-Time Push Notification Output
   └─ File: queue_worker/handlers.py -> Function: _publish_sse_events() (Redis Pub/Sub channel `invoice.update.{batch_id}`)
   └─ File: routers/invoices.py -> Function: stream_invoice_status() -> sse_event_generator() (subscribes to the same channel)
```

**Other intake doors reuse steps 3-10 unchanged:** `POST /email/mailintegration` (Flow 13), `POST /connectors/import/{provider}` (Flow 7), Autopilot sync (Flow 19), and `POST /outbound-invoices/upload` (Flow 14, task `process_outbound_invoice`). Soft delete: `DELETE /invoices/{invoice_id}` -> `delete_invoice()` and `DELETE /invoices/batches/{batch_id}` -> `rollback_batch()` set `deleted_at`, write an `AuditLog(action="DELETE_INVOICE")`, then call `chroma_client.delete_invoice_chunks()` / `delete_document_chunks()` after the commit (Gap 460). Product reads filter through `services/invoice_visibility.invoice_not_deleted()`.

---

## Flow 2: Poll Single Invoice Ingestion Status (Sync Polling)
* **API Endpoint**: `GET /api/v1/invoices/status/{job_id}`

```
1. API Router
   └─ File: routers/invoices.py -> Function: get_invoice_status()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Database Query
   └─ File: dependencies.py -> Function: get_db_session()
```

---

## Flow 3: Semantic Chat & Invoice Query
* **API Endpoint**: `POST /api/v1/chat/sessions/{session_id}/message` (sessions created via `POST /api/v1/chat/sessions`), then `GET /api/v1/chat/jobs/{job_id}/status` (poll) or `GET /api/v1/chat/jobs/{job_id}/stream` (SSE progress).
* **Response Payload** (persisted on `chatmessage`): `content`, `citations`, `generated_sql`, `result_invoice_ids`, and — on attachment turns — `attachment_payload` (confirmation / comparison / suggested actions / evidence).

```
1. API Router
   └─ File: routers/chat.py -> Function: post_chat_message()
      - charge_sandbox_chat_or_402() -> services/sandbox.py::charge_sandbox_chat_message() (sandbox tenants only)
      - Writes the user ChatMessage; optional `attachment_ids` bind Feature 26 attachments to the turn
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Async dispatch (default: ENABLE_ASYNC_CHAT_QUEUE=True, Gap 280)
   └─ File: services/chat_queue.py -> ChatQueueService.enqueue_chat_job()
      - LPUSH to Redis list `chat_tasks_queue`; assistant ChatMessage placeholder status='queued', job_id set
      - Per-tenant ceiling PER_TENANT_MAX_ACTIVE_CHAT = 3 (`chat_inflight:{tenant}`); over it raises
        ChatQueueCapacityError -> HTTP 429 + Retry-After: 5 (Gap 364)
   └─ File: queue_worker/main_worker.py -> _process_redis_chat_tasks() (RPOP) -> queue_worker/handlers.py ->
      handle_process_chat_job() under chat_session_lock() (`chat_session_lock:{session}`, 300 s)
   └─ Progress: ChatQueueService.publish_progress() / complete_job() / fail_job() ->
      `chat_job_status:{job_id}` (TTL 3600 s) + pub/sub `chat_job_channel:{job_id}` -> get_chat_job_status() / stream_chat_job()
   └─ Sync fallback (flag off, and the widget route): routers/chat.py -> run_sync_chat_turn() calls the agent in-request
4. Conversational Routing (plain Python router, not a LangGraph state machine)
   └─ File: agents/query_agent.py -> Function: run_query_agent()
      - Answer cache check: _cache_key(tenant_id, message, rules_version, attachment_ids) ->
        Redis `chat_answer_cache:…` (TTL 3600 s); narrowing follow-ups bypass it (Gap 423 / F6.1 C2)
      - get_chat_history(session_id, db_session, max_tokens=3000) — token-bounded window; older turns are
        condensed once into chatsession.history_summary (Gap 437); chatsession.focus is injected each turn (Gap 436)
      - _chat_rules_block(): Feature 18 TenantChatRule + TenantChatSettings style block
      - Attachment turn (attachment_ids present) -> _run_attached_document_turn() (step 6)
      - Otherwise classify_query() on _fast_llm() -> "SQL" | "RAG" | "CHAT"
5. SQL path (`if route == "SQL"`)
   └─ agents/query_agent.py -> Function: execute_generated_sql(sql, tenant_id, db_session)
      - Tenant-scoped validation on `invoice` (documents are never visible to NL->SQL, E10)
      - _harvest_invoice_ids_via_companion_query() fills chatmessage.result_invoice_ids (Feature 18)
      - Feature 29 full-record route: services/full_records.py -> fetch_full_records() / full_record_block()
        hands the complete rows to _chat_summary_llm() (role `chat_summary`) for narration;
        agents/query_tools.py -> compute() / date_math() do the arithmetic in Python
   └─ RAG path (`if route == "RAG"`, also re-dispatched from SQL on C3): chroma_client.query_invoice_chunks(tenant_id,
      message, limit=5) over `invoice_chunks_{tenant}`; agents/query_tools.bound_document_pages() caps pages per invoice
6. Attached-document path (Feature 26)
   └─ agents/query_agent.py -> _run_attached_document_turn()
      - services/chat_document_search.py -> search_attachment_chunks() over `chat_docs_{tenant}` (content chat is
        gated by ENABLE_GENERIC_DOC_CHAT, default False)
      - services/document_comparison.py -> compare_documents() / reconcile_referenced_documents() /
        check_line_arithmetic() / get_match_policy() -> record_comparison() (table document_comparisons)
7. Output Guardrails
   └─ agents/query_agent.py -> _answer_contract_gate(prose, evidence_numbers) when ENABLE_ANSWER_CONTRACT_GATE=True
      (Feature 29 task 29.9): every figure in the answer must trace to fetched evidence
   └─ Retrieved chunk text is treated as third-party content with per-invoice provenance (Gap 388)
   └─ ENABLE_CHAT_STREAMING (default False; true on dev) streams the phrasing calls token-by-token (F6.1 A3)
8. Quality judge & telemetry
   └─ telemetry.py -> `llm_agent_call` per model call, `chat_turn` per turn (App Insights; no LangSmith)
   └─ handlers.py -> services/online_quality_judge.py::submit_turn_judgement() -> judge_turn() when
      ENABLE_PRODUCTION_QUALITY_JUDGE=True (default False; true on dev) -> agent_eval_run rows (run_source='production')
   └─ PUT /chat/messages/{id}/feedback thumbs-down -> chat_feedback row + auto_golden_cases promotion (Gap 453);
      POST /chat/messages/{id}/triage -> Feature 18 correction flow; POST /chat/rules/preview|commit ->
      services/chat_rules.py::validate_chat_rule() / render_chat_rule() (deterministic, no LLM) -> tenant_chat_rules
```

---

## Flow 4: Audit Resolution (Approve/Reject Invoice & Dismiss Alerts)
* **API Endpoints**: `PUT /api/v1/audit/resolve/{invoice_id}` (inbound) and `PUT /api/v1/outbound-audit/resolve/{invoice_id}` (outbound)
* **Payload**: `status` — `PAID`, `REJECTED`, `AUDIT_REQUIRED` (reopen), or the Gap 407 non-terminal deferrals `REVIEW_LATER` / `NEEDS_RESUBMISSION` (refused on an already `PAID`/`REJECTED` row) — plus `dismissed_alerts`. Both routers are mounted with `dependencies=[Depends(require_actions_scope)]`, so an API key needs `tenant.api_key_scope='actions'`.

```
1. API Router
   └─ File: routers/audit.py -> Function: resolve_audit_invoice()
      - Filters invoice.sa_alerts to drop entries matching dismissed_alerts (by id, type, or message)
      - Sets invoice.status to the target status; rows are read through invoice_not_deleted()
      - audit.py also imports queue_worker/handlers._run_ocr() and agents/extraction_agent.run_extraction_agent()
        for an in-request re-extraction helper (L237 / L306)
   └─ File: routers/outbound_audit.py -> Function: resolve_outbound_alert() (utils/rule_schema.py alert vocabulary)
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context() + require_actions_scope
3. Database Session
   └─ File: dependencies.py -> Function: get_db_session()
4. Audit Log
   └─ Writes an AuditLog row in the same transaction: action="RESOLVE_INVOICE", or "REOPEN_INVOICE" when the
     target is AUDIT_REQUIRED; outbound writes "RESOLVE_OUTBOUND_INVOICE"
5. Fan-out after commit (each best-effort, never fails the resolve)
   └─ services/webhooks.py -> dispatch_webhook_event() (invoice.approved / invoice.rejected …)
   └─ services/workflow_outputs.py -> deliver_email_summary() (CSV + JSON via services/invoice_export.py, Gap 339)
     and deliver_drive_archive() (Feature 25 Drive write-back via utils/connector_files.upload_google_drive_file())
   └─ services/staff_notify.py -> notify_auditor_action()
6. Trainer Agent Feedback Loop
   └─ **[Not implemented]** Auditor corrections do not trigger agents/trainer_agent.py. Template learning happens
     only through the /trainer/* flow (Flow 6); Feature 18's chat-side correction flow is on Flow 3 step 8.
```

---

## Flow 5: Dashboard Analytics & Performance Metrics
* **API Endpoints**: `GET /api/v1/dashboard/metrics`, `GET /dashboard/trainer-impact`, `GET /dashboard/insights`, `POST /dashboard/insights/dismiss`; outbound: `GET /api/v1/outbound-dashboard/invoices`, `GET /outbound-dashboard/metrics`

```
1. API Router
   └─ File: routers/dashboard.py -> Function: get_dashboard_metrics() (INBOUND rows only — Gap 329 flow_direction filter)
   └─ File: routers/dashboard.py -> Function: get_trainer_impact()
   └─ File: routers/dashboard.py -> Function: get_dashboard_insights() -> utils/llm.get_llm() wrapped in
      telemetry.tracked_llm_call(); cached in Redis `dashboard_insights:{tenant}` (TTL 3600 s);
      dismiss_dashboard_insight() -> `dashboard_insights_dismissed:{tenant}`; invalidate_insights_cache() on data change
   └─ File: routers/outbound_dashboard.py -> list_outbound_invoices() / get_outbound_dashboard_metrics()
      (OUTBOUND rows; OVERDUE = SENT past due_date, computed at read time)
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. SQL Database session aggregates
   └─ File: dependencies.py -> Function: get_db_session(); rows filtered by services/invoice_visibility.invoice_not_deleted()
      - Aggregation is done in Python over the fetched Invoice rows, not via SQL GROUP BY
```

---

## Flow 6: Trainer Sandbox & Rules Registry (Conversational Feedback Loop)
* **API Endpoints**: `POST /api/v1/trainer/upload` (transient parse), `POST /trainer/sessions/from-invoice` (start from a production invoice), `POST /trainer/sessions/{session_id}/chat` (correction), `POST /trainer/sessions/{session_id}/corrections/{tolerance|confidence-threshold|alert-override|missed-alert}` (Feature 18 alert-anchored corrections), `POST /trainer/sessions/{session_id}/preview`, `POST /trainer/sessions/{session_id}/commit`, `GET /trainer/templates/history`, `POST /trainer/templates/{template_id}/rollback/{version}`, `GET /trainer/chat-style`, `POST /trainer/sessions/{session_id}/commit-behavior`. `POST /trainer/sessions/global` and `/sessions/from-production` return **410 Gone** (Global-scope rule creation removed by Feature 18). Whole router gated by `require_can_train`; `require_paid_plan()` (services/billing_lifecycle.PAID_PLANS) on paid-only endpoints.

```
1. API Router (Transient Upload)
   └─ File: routers/trainer.py -> Function: upload_transient_file()
      - services/file_intake.normalize_upload() -> queue_worker/handlers._run_ocr() -> agents/extraction_agent.run_extraction_agent()
      - Session state is stored in Redis by services/trainer_sessions.py (save_session / get_session /
        update_session / delete_session; key `trainer:session:{id}`, SESSION_TTL_SECONDS = 3600) — shared across
        replicas; the old in-process TRAINER_SESSIONS dict is gone
2. API Router (Chat Feedback)
   └─ File: routers/trainer.py -> Function: trainer_chat()
   └─ File: agents/trainer_agent.py -> Function: run_trainer_agent() -> refine_constraints() (utils/llm.get_llm();
      raises ConstraintRefinementError); utils/rule_schema.py + utils/alert_registry.py define the rule/alert vocabulary
   └─ File: routers/trainer.py -> preview_session_rules() -> services/rule_impact.py::compute_rule_impact() /
      describe_rule() / new_rules() (deterministic before/after diff, no LLM)
3. API Router (Commit Rules)
   └─ File: routers/trainer.py -> Function: trainer_commit()
      - Saves to ExtractionTemplate (per-vendor or tenant Global, flow_direction-aware, version += 1) and appends an
        ExtractionTemplateVersion row; rollback_template() restores a prior version the same way
      - Invalidates the chat answer cache (`chat_answer_cache:{tenant}:*`)
      - _enqueue_reaudit(tenant_id, vendor_name) -> Azure Storage Queue task "reaudit_templates" ->
        queue_worker/handlers.handle_reaudit_templates() re-audits that vendor's existing invoices
        (the re-audit trigger that was "[Not yet implemented]" in 2026-07 exists)
4. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context() + require_can_train
```

---

## Flow 7: Ingest from Integrations (Google Drive)

> **Salesforce removed 2026-08-28 — see Gap 334.** Google Drive is the only connector. The
> `list_salesforce_libraries`/`list_salesforce_files`/`verify_salesforce_instance`/
> `download_salesforce_file` functions and every Salesforce branch in `routers/connectors.py`,
> `queue_worker/handlers.py`, and `services/autopilot_sync.py` no longer exist. Root causes:
> cross-org OAuth structurally blocked (External Client App, Distribution State = Local) and a
> wrong data model (browsed Libraries/`ContentWorkspace`; real invoices live on
> Account/Opportunity records).
* **API Endpoints**: `GET /api/v1/connectors/status`, `GET /connectors/auth-url/{provider}`, `GET /connectors/callback/{provider}`, `GET /connectors/files/{provider}`, `POST /connectors/import/{provider}`, `DELETE /connectors/{provider}`

```
1. Status Check
   └─ File: routers/connectors.py -> Function: get_connectors_status()
2. Initiating Integration Auth
   └─ File: routers/connectors.py -> Function: get_auth_url()
      - Real Google OAuth consent URL when utils/connector_oauth.has_real_credentials("google_drive", settings) (Gap 98)
3. OAuth Callback Handler
   └─ File: routers/connectors.py -> Function: oauth_callback()
   └─ Encryption: utils/encryption.py -> Function: encrypt_token()
   └─ Database Write: adds/updates a TenantConnection record (provider='google_drive')
4. Remote Folder Browsing
   └─ File: routers/connectors.py -> Function: list_connector_files()
   └─ utils/connector_oauth.py -> get_valid_access_token() (decrypt_token(), refresh if expired) ->
      utils/connector_files.py -> list_google_drive_files()
5. Async Import Task Trigger
   └─ File: routers/connectors.py -> Function: trigger_file_import()
      - services/billing_quota.charge_free_quota(); Azure Storage Queue task "import_connector_file"
   └─ File: queue_worker/handlers.py -> Function: handle_import_connector_file()
      - utils/connector_files.download_google_drive_file() (real bytes), then handle_process_invoice() (Flow 1)
6. Disconnect
   └─ File: routers/connectors.py -> Function: disconnect_connector()
```

**Note:** Provider logic lives in `utils/connector_oauth.py` (token exchange/refresh, `google_granted_scopes()`, `token_has_drive_write_scope()`) and `utils/connector_files.py` (`list_google_drive_files`, `download_google_drive_file`, `upload_google_drive_file`, `find_or_create_google_drive_folder` — the last two serve Feature 25's Drive archive write-back). There is no per-provider module directory; Google Drive is the only provider.

---

## Flow 8: Chat Attached Documents (Feature 26, router added 2026-09-01)
* **API Endpoints**: `POST /api/v1/chat/sessions/{session_id}/attachments`, `POST /chat/attachments/{attachment_id}/confirm-matches`, `GET /chat/attachments/{attachment_id}`

```
1. API Router
   └─ File: routers/chat_attachments.py -> Function: upload_chat_attachment()
      - services/storage.upload_pdf_to_blob_storage() -> chat_attachments row (extraction_status='PENDING', 10 MB cap,
        expires_at = created_at + CHAT_ATTACHMENT_TTL_DAYS)
      - services/chat_queue.ChatQueueService.enqueue_attachment_extraction() -> Redis `chat_tasks_queue`
        {"task": "extract_attachment"}; if the queue is unavailable, extract_attachment() runs in-request
2. Worker
   └─ File: queue_worker/handlers.py -> Function: handle_extract_attachment(job_id, attachment_id, tenant_id)
   └─ File: services/attachment_extraction.py -> extract_attachment() (agents/extraction_agent REFERENCE profile) ->
      index_attachment() (services/chat_document_search.index_attachment_chunks() -> `chat_docs_{tenant}`,
      chunk_count/indexed_at on the row) -> match_attachment() (services/document_comparison.find_candidate_invoices();
      match_tier/match_summary, Gap 444/452)
3. Confirmation gate (D4)
   └─ File: routers/chat_attachments.py -> Function: confirm_attachment_matches() sets confirmed_invoice_ids;
      the chat turn then runs Flow 3 step 6
4. Lifecycle
   └─ DELETE /chat/sessions/{id} -> services/chat_document_search.delete_attachment_chunks();
      scripts/sweep_chat_attachments.py deletes expired rows (chunks -> blob -> row)
```

---

## Flow 9: Non-Invoice Documents (Feature 27, router added 2026-09-05)
* **API Endpoints**: `GET /api/v1/documents`, `GET /documents/{document_id}`, `DELETE /documents/{document_id}`

```
1. API Router
   └─ File: routers/documents.py -> list_documents() / get_document() / delete_document()
      - Reads the `documents` table (status EXTRACTED | EXTRACT_FAILED), tenant-scoped, deleted_at IS NULL
      - delete_document(): sets deleted_at, commits, then chroma_client.delete_document_chunks() (best-effort)
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
```
Rows are written only by `queue_worker/handlers.handle_process_invoice()` (Flow 1 step 6, non-invoice branch).

---

## Flow 10: Ingestion History (Gap 464, router added 2026-09-05)
* **API Endpoints**: `GET /api/v1/ingestion-history`, `GET /ingestion-history/{run_id}/files`, `POST /ingestion-history/archive-all`, `POST /ingestion-history/{run_id}/archive`, `POST /ingestion-history/{run_id}/unarchive`

```
1. API Router
   └─ File: routers/ingestion_history.py -> list_ingestion_history() / get_ingestion_run_files()
      - Runs come from `ingestion_batches` (manual / email / connector), `tenant_autopilot_logs` (autopilot runs, read
        through unchanged) and `dropped_inbound_emails` (REJECTED runs); per-file outcomes are derived at read time
        from `invoice` and `documents` rows sharing the batch_id
   └─ archive_all_ingestion_history() / archive_ingestion_run() / unarchive_ingestion_run() set/clear
      ingestion_batches.archived_at and dropped_inbound_emails.archived_at (a hide, never a delete)
2. Writers
   └─ services/ingestion_batches.py -> record_ingestion_batch() called from routers/invoices.py,
      routers/outbound_invoices.py and routers/email_ingestion.py at the door
```

---

## Flow 11: Feature Flags for the FE (Feature 27 R5(a))
* **API Endpoint**: `GET /api/v1/config/features`

```
1. API Router
   └─ File: routers/config_features.py -> Function: get_feature_flags()
      - Returns every settings attribute whose name begins `ENABLE_` and its current value (read-only; not an
        arbitrary config reader). Consumed by invoice-fe `lib/featureFlags.ts::loadFeatureFlags()`
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
```

---

## Flow 12: Settings — Service Flow, API Keys, Widget Tokens, Workflow (Features 16 / 25)
* **API Endpoints**: `GET/PUT /api/v1/settings/vendor-flow`, `GET /settings/security/api-key`, `POST /settings/security/api-key/rotate`, `GET /settings/security/api-key/verify`, `GET/PUT /settings/workflow`, `GET/POST /settings/security/widget-tokens`, `DELETE /settings/security/widget-tokens/{token_id}`

```
1. Service flow toggles
   └─ File: routers/settings.py -> get_vendor_flow_settings() / update_vendor_flow_settings()
      (tenant.receive_invoices_enabled / send_invoices_enabled; outbound needs pro_combined + a registered
      outbound sender via services/staff_notify.list_registered_emails())
2. API key (one per tenant, Gap 184)
   └─ File: routers/settings.py -> get_api_key_status() / rotate_api_key() / verify_api_key_endpoint()
   └─ File: services/api_keys.py -> generate_api_key() (inv_live_), generate_salt(), hash_api_key() (PBKDF2-HMAC-SHA256),
      verify_api_key(), key_prefix(), masked_display(); raw key returned exactly once
   └─ Resolution on every request: dependencies.py -> resolve_api_key_context() -> permissions_for_key_scope(tenant.api_key_scope)
3. Workflow wizard (Feature 25, Gap 336)
   └─ File: routers/settings.py -> get_workflow_settings() / update_workflow_settings()
      - PUT writes tenant_workflow_configs AND tenant.api_key_scope in one transaction; GET derives audit_policy
        from tenant.api_key_scope; _validate_destinations() rejects 'drive_archive' (422) and requires a
        TenantEmailSender for 'email_summary'; services/sandbox.is_sandbox_tenant() blocks sandbox tenants
4. Widget tokens (Feature 25, Gap 341)
   └─ File: routers/settings.py -> list_widget_tokens() / create_widget_token() / delete_widget_token()
   └─ File: services/widget_tokens.py -> issue_widget_token(), active_widget_tokens(), revoke_widget_token()
      (services/api_keys.generate_widget_token() -> inv_widget_)
```

---

## Flow 13: Email-In Ingestion (Feature 14)
* **API Endpoints**: `GET /api/v1/email/settings/mailbox`, `GET/POST /email/settings/email-senders`, `DELETE /email/settings/email-senders/{sender_id}`, `POST /email/mailintegration` (public — SendGrid Inbound Parse relayed through invoice-website)

```
1. Tenant settings
   └─ File: routers/email_ingestion.py -> get_mailbox() (EMAIL_APP_ADDRESS), list_email_senders() / add_email_sender() /
      delete_email_sender() (tenant_email_senders, email unique platform-wide, email_set inbound|outbound)
2. Inbound webhook (fail-closed)
   └─ File: routers/email_ingestion.py -> Function: email_mailintegration_webhook()
      - services/inbound_mail_security.py -> verify_inbound_secret() (shared secret), oversize_from_content_length()
        (25 MiB cap before the multipart is parsed), record_dropped_email() on every rejection path -> dropped_inbound_emails
      - Sender resolved via TenantEmailSender.email -> tenant_id + flow direction
      - services/file_intake.normalize_upload() -> services/storage.upload_pdf_to_blob_storage() -> Invoice row ->
        Azure Storage Queue "process_invoice" (Flow 1 step 4) -> services/ingestion_batches.record_ingestion_batch(trigger="email")
```

---

## Flow 14: Outbound (AR) Invoices & Invoice Builder (Features 2.1 / 17)
* **API Endpoints**: `POST /api/v1/outbound-invoices/upload`, `GET /outbound-invoices/{invoice_id}/build-defaults`, `POST /outbound-invoices/build/preview`, `POST /outbound-invoices/build`, `PUT /outbound-invoices/{invoice_id}/confirm-send`, `PUT /outbound-invoices/{invoice_id}/mark-paid`

```
1. Upload
   └─ File: routers/outbound_invoices.py -> Function: upload_outbound_invoice()
      - services/file_intake.normalize_upload(), services/billing_quota.charge_free_quota(), Invoice row
        (flow_direction='OUTBOUND', status UPLOADED), Azure Storage Queue task "process_outbound_invoice",
        services/ingestion_batches.record_ingestion_batch()
   └─ File: queue_worker/outbound_handlers.py -> Function: handle_process_outbound_invoice()
      - queue_worker/handlers._run_ocr() -> agents/outbound_extraction_agent.run_outbound_extraction_agent()
        (thin wrapper that calls run_extraction_agent() with the OUTBOUND profile, Gap 283) -> VERIFIED | NEEDS_REVIEW
      - chroma_client.index_invoice_document() when should_index_status(); services/staff_notify.notify_processing_complete()
2. Invoice Builder (clone & edit)
   └─ File: routers/outbound_invoices.py -> get_build_defaults() / preview_built_invoice() / build_outbound_invoice()
   └─ File: services/invoice_builder.py (pure totals core) -> services/pdf_render.py (the only renderer since Gap 462;
      services/pdf_substitute.py was deleted) -> new Invoice row with source_invoice_id + builder_intent (+ notes, Gap 467)
      -> utils/verification_tools.verify_builder_readback() compares intent with the extractor's read-back
3. Lifecycle transitions
   └─ confirm_send_outbound_invoice(): VERIFIED -> SENT, sent_at; mark_outbound_invoice_paid(): SENT -> PAID, paid_at;
      both gated by require_actions_scope (can_audit for humans, `actions` scope for API keys);
      services/staff_notify.notify_auditor_action(); services/webhooks.dispatch_webhook_event()
```

---

## Flow 15: Outbound Webhooks (Feature 15)
* **API Endpoints**: `GET /api/v1/webhooks`, `POST /webhooks`, `PUT /webhooks/{webhook_id}`, `GET /webhooks/{webhook_id}/deliveries`, `DELETE /webhooks/{webhook_id}`

```
1. Subscription CRUD
   └─ File: routers/webhooks.py -> list_webhooks() / create_webhook() / update_webhook() / delete_webhook()
      - services/webhooks.validate_webhook_target_url() (InvalidWebhookUrlError -> 422); secret shown once
   └─ list_webhook_deliveries() reads webhook_delivery_logs (Gap 194)
2. Delivery
   └─ File: services/webhooks.py -> dispatch_webhook_event(db_session, tenant_id, event_type, payload)
      -> Azure Storage Queue task "deliver_webhook" -> queue_worker/handlers.handle_deliver_webhook() ->
      services/webhooks.deliver_webhook_now() (build_delivery_body(), HMAC `X-Webhook-Signature`, 3 attempts) ->
      record_delivery_result() (per-event failure counts, auto-disable after 10)
3. Documentation
   └─ File: routers/webhook_docs.py -> 7 payload schemas (invoice.completed, invoice.audit_required, invoice.approved,
      invoice.rejected, outbound_invoice.sent, outbound_invoice.overdue, outbound_invoice.approved) in the OpenAPI
      "webhooks" section; nothing is mounted
```

---

## Flow 16: Authentication & Provisioning (Feature 1 / 1.1)
* **API Endpoints**: `GET /auth/me`, `POST /auth/provision`, `POST /auth/logout` (mounted without `/api/v1`)

```
1. API Router
   └─ File: routers/auth.py -> get_current_user_context() (get_tenant_context_allow_unpaid) / provision_tenant() / logout()
   └─ provision_tenant(): dependencies.get_authenticated_clerk_identity() -> _create_tenant_with_unique_domain()
      (`.invalid` suffix on domain collision) -> models.RoleMapper.normalize_role() / resolve_permissions()
      (Admin | Auditor | Trainer; fallback "Restricted", Gap 337) -> _seed_admin_email_sender() ->
      _mint_provisioning_api_key() (services/api_keys) -> _tenant_adoption_blockers() (Gap 133: a domain-matched
      legacy tenant that still holds a plan, connections or invoices is never adopted; a fresh tenant is created instead)
2. Per-request context
   └─ File: dependencies.py -> verify_clerk_jwt() (JWKS via get_jwk()) -> reconcile_role_with_org() ->
      get_tenant_context(); API keys -> resolve_api_key_context() (inv_live_ / inv_test_, tenant.api_key_scope);
      widget tokens -> WidgetContext (Flow 22)
```

---

## Flow 17: Billing (Feature 11, PayU)
* **API Endpoints**: `GET /api/v1/billing/usage`, `POST /billing/cancel`, `POST /billing/reactivate`, `POST /billing/create-checkout-session`, `POST /billing/payu/success`, `POST /billing/payu/failure`

```
1. API Router
   └─ File: routers/billing.py -> get_billing_usage() / cancel_subscription() / reactivate_subscription() /
      create_checkout_session() / payu_success() / payu_failure()
      - _request_hash() / _response_hash() (PayU classic hash API), _verify_payment_with_payu(txnid),
        _handle_payu_callback() (relayed through invoice-website `/api/v1/billing/payu/{success,failure}`)
2. Lifecycle
   └─ File: services/billing_lifecycle.py -> extend_paid_through(), request_cancellation(), undo_cancellation(),
      is_lapsed() / enforce_lapse() / sweep_lapsed_tenants() (Gap 71), refresh_free_quota() / sweep_free_quotas() (Gaps 118/121)
   └─ File: services/billing_quota.py -> count_billable_uploads(), charge_free_quota() (row-locked, every intake door)
```

---

## Flow 18: Admin Console (Feature 1.1 / FE Feature 16)
* **API Endpoints**: `GET /api/v1/admin/users`, `PUT /admin/users/{user_ref}/permissions`, `DELETE /admin/users/{user_ref}`, `GET /admin/dropped-emails` — whole router gated by `require_admin`

```
1. API Router
   └─ File: routers/admin.py -> list_tenant_users() / set_user_permissions() (role + can_train/can_audit/can_load/
      can_send_invoices) / remove_tenant_user() / list_dropped_emails() (dropped_inbound_emails, platform-wide record;
      services/inbound_mail_security.sender_domain_of() for unattributed rows)
```

---

## Flow 19: Tenant Autopilot (Feature 13)
* **API Endpoints**: `GET/PUT /api/v1/autopilot/config`, `POST /autopilot/sync`, `GET /autopilot/history`, `GET /autopilot/history/legacy/files`, `GET /autopilot/history/{batch_id}/files`, `DELETE /autopilot/history`, `DELETE /autopilot/history/{batch_id}`

```
1. API Router
   └─ File: routers/autopilot.py -> get_autopilot_config() / upsert_autopilot_config() (valid_sources = {"gdrive"};
      history_retention_days 7..365) / trigger_sync() / get_autopilot_history() / get_run_files() / get_legacy_run_files() /
      hide_all_autopilot_history() / hide_autopilot_run() (tenant_autopilot_logs.hidden_at, Gap 429)
2. Sync
   └─ File: services/autopilot_sync.py -> run_sync(tenant_id, db_session, trigger="manual"|"scheduled")
      - utils/connector_files.list_google_drive_files() / download_google_drive_file(); two-layer dedup on
        tenant_autopilot_logs (source_file_id, content_hash); Invoice row + _dispatch_queue() -> "process_invoice"
        (Flow 1); one TenantAutopilotLog row per file (batch_id, trigger, source_file_name — Gap 427) or a
        NO_NEW_FILES marker; services/staff_notify.notify_autopilot_sync_summary()
   └─ Scheduled: scripts/autopilot_job.py -> run_sync_for_all_due_tenants(); prune_autopilot_history() hard-deletes
      noise rows older than history_retention_days
```

---

## Flow 20: Support Tickets & AI Support Assistant (Feature 19 / Website Feature 5)
* **API Endpoints**: `POST /api/v1/support/chat`, `POST /support/contact` (public), `POST /support/ticket`, `GET /support/tickets`

```
1. API Router
   └─ File: routers/support.py -> support_chat_assistant() -> agents/support_agent.py::evaluate_support_query()
      (retrieval only: chroma_client.get_embeddings() against the shared Chroma collection `support_knowledge_topics`,
      seeded from KNOWLEDGE_TOPICS on first use — no LLM call in this module)
   └─ submit_contact_inquiry() (public; Redis rate limit `support:contact:ratelimit:ip|email`, 5 / 300 s) and
      submit_app_ticket() -> supportticket row (INQ-/TICK- numbers, Gap 251) ->
      services/support_email.dispatch_support_ticket_email() (SendGrid, SUPPORT_NOTIFY_EMAIL + acknowledgement)
   └─ list_support_tickets() (tenant-scoped; anonymous rows never returned)
```

---

## Flow 21: Sandbox Keys (Feature 25, Gap 340 — router added 2026-08-30, LIVE-FLAG-OFF)
* **API Endpoints**: `POST /api/v1/sandbox/keys` (public), `GET /sandbox/keys/me`, `POST /sandbox/claim` — the whole router 404s unless `SANDBOX_KEYS_ENABLED=True` (default False; not set in bicep)

```
1. API Router
   └─ File: routers/sandbox.py -> issue_sandbox_key() (Redis `sandbox:issue:ratelimit:`, global unclaimed cap, fail-closed) ->
      services/api_keys.generate_sandbox_key() (inv_test_) -> services/sandbox.py::issue_sandbox_tenant()
      (fresh real Tenant with domain `sandbox-<id>.invalid`, sandbox_tenants row, expires_at = SANDBOX_KEY_TTL_HOURS)
   └─ get_sandbox_status() (authenticated by the key itself; chat_messages_used)
   └─ claim_sandbox() -> services/sandbox.claim_sandbox_tenant() (compare-and-set on claimed_at, mints an inv_live_ key)
2. Expiry
   └─ dependencies.resolve_api_key_context() refuses expired keys; scripts/sweep_sandbox_tenants.py hard-deletes
      expired unclaimed tenants (delete_attachment_chunks(), delete_tenant_document_collection())
```

---

## Flow 22: Embedded Chat Widget (Feature 25, Gap 341 — router added 2026-08-30)
* **API Endpoint**: `POST /api/v1/widget/chat/message` — the only route reachable by an `inv_widget_` token

```
1. Middleware & context
   └─ File: routers/widget.py -> WidgetCORSMiddleware; get_widget_context() -> services/api_keys.looks_like_widget_token() ->
      services/widget_tokens.resolve_widget_token() (token_prefix lookup, PBKDF2 verify, revoked_at) ->
      origin_is_allowed() (defence in depth) -> dependencies.WidgetContext (no role, no scope, no permissions)
2. Turn
   └─ File: routers/widget.py -> Function: post_widget_chat_message()
      - Creates a ChatSession/ChatMessage, routers/chat.charge_sandbox_chat_or_402(), then
        routers/chat.run_sync_chat_turn() — the synchronous Flow 3 path, in-request
```

---

## Queue Worker & Background Jobs

**Queue worker** (`queue_worker/`, container app `queue-worker`): `main_worker.py::poll_queue()` polls Azure Storage Queue `extraction-tasks-queue` with `MAX_WORKERS = 10` threads and a Redis per-tenant fair share (`PER_TENANT_MAX_INFLIGHT = 3`, key `inflight:{tenant}`); `_process_message()` dispatches on the message's `task` field and routes a message to `extraction-tasks-deadletter-queue` after `MAX_DEQUEUE_ATTEMPTS = 5`. The same loop also drains the Redis list `chat_tasks_queue` via `_process_redis_chat_tasks()`.

| Task name | Source queue | Handler |
| :--- | :--- | :--- |
| `process_invoice` | Storage Queue | `queue_worker/handlers.py::handle_process_invoice()` (Flow 1) |
| `process_outbound_invoice` | Storage Queue | `queue_worker/outbound_handlers.py::handle_process_outbound_invoice()` (Flow 14) |
| `import_connector_file` | Storage Queue | `handlers.py::handle_import_connector_file()` (Flow 7) |
| `reaudit_templates` | Storage Queue | `handlers.py::handle_reaudit_templates()` (Flow 6) |
| `deliver_webhook` | Storage Queue | `handlers.py::handle_deliver_webhook()` (Flow 15) |
| `process_chat_job` (also the default when `task` is absent) | Redis `chat_tasks_queue` | `handlers.py::handle_process_chat_job()` (Flow 3) |
| `extract_attachment` | Redis `chat_tasks_queue` | `handlers.py::handle_extract_attachment()` (Flow 8) |

**Scheduled jobs** (ACA jobs from `infra/08-apps.bicep` and the standalone `infra/*-job-only.bicep` templates, module `infra/modules/compute/scheduled-job.bicep`; every entry point is under `apps/invoice-be/scripts/`):

| Job | Entry point | Schedule (bicep param / default) | What it does |
| :--- | :--- | :--- | :--- |
| `caj-benchmark-eval` (nightly) | `run_extraction_benchmark.py --mode live --no-write --no-gate --json --run-label nightly …` && `run_agent_eval.py --paths default --run-label nightly` | `benchmarkEvalCron` | Feature 23 Phase 3: extraction benchmark + golden-bank chat eval -> `agent_eval_run` (`run_source='golden'`), `services/ops_recommendation.run_recommendation_pass()` on `--run-label nightly`; deployed on dev |
| `caj-online-signals` | `emit_online_signals_job.py --window-hours 6` (`emit-online-signals-job-only.bicep`) | `onlineSignalsCron` | `services/online_eval_signals.compute_online_signals()` / `emit_online_signals()` (zero-result, slow-turn, thumbs-down clustering, clarification, budget-exhaustion rates) -> App Insights; deployed on dev |
| `caj-chat-doc-ttl` | `sweep_chat_attachments.py` (`chat-doc-ttl-job-only.bicep`) | `chatDocTtlCron` | Feature 26 E-7/H8: expire `chat_attachments` past `expires_at` (chunks -> blob -> row) |
| `caj-billing-lifecycle` | `sweep_billing_lifecycle.py` (wraps `sweep_lapsed_billing.py` + `sweep_free_quotas.py`) | `'0 6 * * *'` | `services/billing_lifecycle.sweep_lapsed_tenants()` + `sweep_free_quotas()`; template exists, **not deployed on dev** per tracker 2026-08-30 |
| `caj-overdue-sweep` | `sweep_outbound_overdue.py` | `overdueSweepCron` (module default `'0 2 * * *'`) | `services/outbound_overdue.sweep_overdue_invoices()` -> `outbound_invoice.overdue` webhook, `invoice.overdue_notified_at`; **not deployed on dev** |
| `caj-sandbox-sweep` | `sweep_sandbox_tenants.py` | `sandboxSweepCron` | Feature 25: hard-delete expired unclaimed sandbox tenants (+ their Chroma collections); **not deployed on dev** (Gap 357 open) |
| Autopilot | `autopilot_job.py` -> `services/autopilot_sync.run_sync_for_all_due_tenants()` | none — `infra/FLAGS_AND_INFRA_CHECKLIST.md` L48: "not scheduled by any bicep job; runs from the backend scheduler path only" | Feature 13 scheduled Drive sync + `prune_autopilot_history()` |

Scripts with no job definition (run by hand): `reconcile_stuck_invoices.py` (FE Gap 81 stuck-invoice re-enqueue), `sweep_azure_cost.py` (Feature 20 cost snapshot -> telemetry; not scheduled), `reembed_chroma_collections.py` / `migrate_chroma_to_per_tenant.py` (vector migrations), `rescore_agent_eval.py` / `attach_chat_eval.py` / `run_model_matrix.py` / `run_doctype_matrix.py` (Feature 29 / Gap 466 evaluation tooling), `grant_test_plan.py`, `export_clerk_data.py` / `import_clerk_data.py`, `probe_document_injection.py`, `verify_gap280_architecture.py`. **Deleted:** `scripts/ops_digest_job.py` and `services/ops_digest*.py` (Feature 24 Ops Digest, removed 2026-08-25, Gap 311) and the `ops-digest-job-only.bicep` template.

---

## Agents & LLM Layer (`agents/`, `utils/llm.py`, `utils/model_registry.py`)

| Module | Role | LLM role used |
| :--- | :--- | :--- |
| `agents/extraction_agent.py` (2,727 lines) | NOVA extraction graph: `classify_doc_type_node` -> `classify_node` -> `dynamic_qa_node` -> `extract_node` -> `verify_node` -> `route_after_verification` (retry to `extract` or END); direction profiles `INBOUND` / `OUTBOUND` / `REFERENCE` / `GENERIC` with their own `build_*_multimodal_prompt()`; `run_extraction_agent()`, `_compiled_extraction_graph()`, `invoke_with_retry()` | `primary` (`get_llm(max_tokens=profile.max_tokens)`) |
| `agents/outbound_extraction_agent.py` | `run_outbound_extraction_agent()` — thin wrapper over `run_extraction_agent()` with the OUTBOUND profile (Gap 283); not a second graph | `primary` |
| `agents/query_agent.py` (7,698 lines, 125 top-level functions) | SAGE chat: `run_query_agent()`, `classify_query()`, `execute_generated_sql()`, `get_chat_history()`, `_run_attached_document_turn()`, `_answer_contract_gate()`, `_cache_key()`, `_harvest_invoice_ids_via_companion_query()` | `primary` (SQL generation), `fast` (`_fast_llm()`: classify / summary / narration), `chat_summary` (`_chat_summary_llm()`: full-record narration, Feature 29) |
| `agents/query_tools.py` | LLM-free helpers surviving Feature 21: `get_full_record()`, `compute()`, `date_math()`, `parse_results_table()`, `bound_document_pages()` | none |
| `agents/sage_prompts.py` | `PERSONA_BLOCK` + schema-reflection constants consumed by `query_agent.py` | none |
| `agents/trainer_agent.py` | `run_trainer_agent()` -> `refine_constraints()` (`ConstraintList`, `ConstraintRefinementError`) | `primary` (`get_llm()`) |
| `agents/support_agent.py` | `evaluate_support_query()` — embedding retrieval over `support_knowledge_topics` | none (embeddings only) |
| `services/document_type_classifier.py` | Feature 27: `classify_doc_type_deterministic()` then `classify_doc_type()` LLM fallback; 14 `DOC_TYPES`; `derive_rule_era()` | `primary` (`get_llm(max_tokens=512)`) |
| `services/doc_attributes.py` | `derive_direction()`, `derive_correction_method()`, `extract_fiscal_markers()`, `extract_regional_ids()` — deterministic | none |
| `services/agent_eval.py` | LLM-as-judge for the golden bank: `score_faithfulness()`, `score_relevance()`, `score_accuracy()`, deterministic `score_context()` / `score_orchestration()`, `score_persona()`, `score_context_drift()`, `score_answer()`, `decide_pass()` (Feature 29 29.2/29.6 recalibration, Gaps 478/479) | `judge` |
| `services/online_quality_judge.py` | `submit_turn_judgement()` -> `judge_turn()` on real chat turns (flag-gated) -> `agent_eval_run` production rows | `judge` |
| `services/online_eval_signals.py`, `services/ops_recommendation.py` | Online signals and nightly ops recommendations | none / `judge` |
| `agents/README.md` | **Stale** — a generic ReAct blueprint that does not describe the modules above | — |

**Deleted modules (do not reference):** `agents/sage_orchestrator.py` and the `ENABLE_AGENTIC_SAGE` flag + 4 tools (Feature 21 SAGE orchestrator, removed 2026-08-25, Gap 316 — `agent_eval_run` rows with `agent_name='sage.agentic_path'` are historical); `services/ops_digest*.py` (Feature 24, Gap 311); `services/pdf_substitute.py` (Gap 462); Salesforce branches in `routers/connectors.py`, `queue_worker/handlers.py`, `services/autopilot_sync.py` (Gap 334, 2026-08-28).

**Model plumbing.** `utils/llm.py`: `build_llm(provider, model, max_tokens, reasoning_effort, api_version)` for providers `azure` / `ollama` / `mock` (`SUPPORTED_LLM_PROVIDERS`), `get_llm()` (primary), `get_llm_for_role(role)`, `get_chat_summary_llm()`, `get_long_doc_llm()`. Every call is wrapped by `telemetry.tracked_llm_call()` -> App Insights `llm_agent_call` events (no LangSmith). `utils/model_registry.py` (Gap 465, 2026-09-05) is the one place model knowledge lives: `MODEL_CATALOG` (context limit, `max_input_tokens`, tokenizer encoding, `reasoning_capable`, USD/1M prices, `recall_note`), longest-prefix `catalog_entry_for()`, `context_limit_for()` / `max_input_tokens_for()` / `encoding_for()` / `prices_for()` / `cost_usd()`, and `resolve_model(role)` -> `ModelSpec`. Unknown names get `DEFAULT_SPEC` (128k, `o200k_base`, $0) with one warning.

| Role (`Role` literal) | Setting (HEAD `config.py`) | Default | Fallback chain | Dev Azure (`infra/params.dev.json`) | Used by |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `primary` | `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-5-mini` | — | `gpt-5.6-luna` | extraction, SQL generation, trainer, doc-type classifier |
| `fast` | `AZURE_OPENAI_FAST_DEPLOYMENT_NAME` | `""` | -> primary | `gpt-5.6-luna` | `_fast_llm()` classify / summary (F6.1 A2) |
| `judge` | `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME` | `""` | -> primary | `gpt-5-mini` | `agent_eval.py`, `online_quality_judge.py` |
| `chat_summary` | `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME` | `""` | -> judge -> primary | `gpt-5-mini` | full-record chat narration (Feature 29 decision 2) |

Catalog entries: `gpt-6-astra` (deployment deleted 2026-09-06), `gpt-5.6-luna` (1,050,000 ctx / 922,000 input, $0.20/$1.20; weak long-context recall), `gpt-5.6-terra` ($2/$12, `long_doc` candidate), `gpt-5.6-sol` (deleted), `gpt-5-mini`, `gpt-5-nano`, `gpt-5`, `gpt-4o-mini` / `gpt-4o` / `gpt-3.5-turbo` (retiring; kept for historical pricing), `llama3.2` / `llama3` (Ollama), `mock`. `AZURE_OPENAI_API_VERSION = "2024-10-21"` (Gap 465; `2024-02-15-preview` is gone). Non-LLM models: `DOC_INTEL_MODEL_ID = "prebuilt-invoice"`, `EMBEDDING_MODEL_NAME = "BAAI/bge-m3"`, `OLLAMA_MODEL = "llama3.2:latest"` (local provider only). SQL reasoning knobs (F6.1 A1): `AZURE_OPENAI_SQL_REASONING_EFFORT = ""`, `AZURE_OPENAI_SQL_MAX_COMPLETION_TOKENS = 0` (unset).

---

## Feature Flags (`config.py` at HEAD `d9b6ce2`, defaults vs dev Azure)

`GET /api/v1/config/features` (Flow 11) publishes every `ENABLE_*` value below to the FE.

| Flag | Line | Default | Dev Azure (`params.dev.json`) | Gates |
| :--- | :--- | :--- | :--- | :--- |
| `ENABLE_ASYNC_CHAT_QUEUE` | L68 | `True` | `true` | Redis chat job queue (Flow 3 step 3); the only path with progress SSE and the per-tenant ceiling (Gap 364) |
| `ENABLE_CHAT_STREAMING` | L86 | `False` | `true` | F6.1 A3 token streaming of the phrasing calls |
| `ENABLE_GENERIC_EXTRACTION` | L201 | `True` — **pinned, "never set False"** (Gap 461, 2026-09-05; the Gap 468 deletion of the flag was reverted) | `true` | Feature 27 `classify_doc_type` node + `documents` routing |
| `ENABLE_ANSWER_CONTRACT_GATE` | L301 | `True` | not in bicep (default applies) | Feature 29 29.9 figure-in-evidence gate |
| `ENABLE_GENERIC_DOC_CHAT` | L390 | `False` | `true` | Feature 26 Part 2 content chat over `chat_docs_{tenant}` |
| `ENABLE_PRODUCTION_QUALITY_JUDGE` | L675 | `False` | `true` | Judge every real chat turn (2 extra `judge` calls) |
| `SANDBOX_KEYS_ENABLED` | L230 | `False` | not in bicep -> False | Feature 25 sandbox router (Flow 21) |
| `ALLOW_MOCK_AUTH` | L23 | `False` | — | test-only auth bypass |
| `MOCK_EMBEDDINGS` | L415 | `False` | — | test-only fake vectors |

Related knobs: `SANDBOX_KEY_TTL_HOURS = 72` (L235), `CHAT_ATTACHMENT_TTL_DAYS = 30` (L280), `LLM_PROVIDER = "azure"` (L422).

> **Uncommitted, not live (2026-09-07):** the working tree's `config.py` adds `ENABLE_ENTITY_RESOLVER`, `ENABLE_SEMANTIC_VIEWS`, `ENABLE_CERTIFIED_EXAMPLES`, `ENABLE_KNOWLEDGE_LAYER` and `ENABLE_RERANK` (all default `False`) from a concurrent Feature 29 phase-2 session. They are **in progress, uncommitted 2026-09-07** and are intentionally excluded from the table above; reconcile once that work lands.
