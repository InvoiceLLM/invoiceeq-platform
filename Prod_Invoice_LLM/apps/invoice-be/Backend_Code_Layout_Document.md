# API Flow Directory & Code Mapping

This document maps each system API to its sequential file and function execution path, reconciled against the actual `apps/invoice-be` implementation (last verified 2026-07-12). Steps marked **[Not yet implemented]** describe intended/roadmap behavior that does not exist in code yet — see the corresponding `be_features/*.md` file for tracked status.

---

## Flow 1: Ingest & Extract Invoice (Async Pipeline)
* **API Endpoints**: `POST /api/v1/invoices/upload` (Upload) & `GET /api/v1/invoices/stream/{batch_id}` (SSE status stream)

```
1. API Router
   └─ File: routers/invoices.py -> Function: upload_invoices()
      - Computes SHA-256 file hash and short-circuits to a DUPLICATE record if a match exists for the tenant (Layer 1 dedup)
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Storage & DB write
   └─ File: services/storage.py -> Function: upload_pdf_to_blob_storage()
   └─ Note: known bug — routers/invoices.py currently calls this function synchronously and passes its *return value*
     into run_in_threadpool() instead of passing the callable, which raises on every non-duplicate upload. See feature_2_pipeline.md.
4. Async Task Queue (Dispatched)
   └─ File: workers/tasks.py -> Function: process_invoice_task()
5. OCR / Layout Extraction
   └─ File: workers/tasks.py -> Function: _run_ocr()
      - Local dev: pypdf text extraction. Production: Azure Document Intelligence `prebuilt-layout` model
        (not the invoice-specific `prebuilt-invoice` model — see feature_5_extraction.md recommendation)
6. Multi-Modal Extraction & Verification (LangGraph, 2 nodes)
   └─ File: agents/extraction_agent.py -> Function: run_extraction_agent()
      - extract_node(): structured LLM extraction (OCR text + base64 page images)
      - verify_node(): calls verify_line_items_math() / verify_totals_math() from utils/verification_tools.py
      - No retry/self-correction loop back to extract_node on validation failure yet — see feature_5_extraction.md
7. Template Rule Lookup (not an agent tool — happens in the worker before re-running extraction)
   └─ File: workers/tasks.py -> queries ExtractionTemplate table, falls back to config/default_templates.json
8. Local Vector Calculation & Storage (only runs if status == COMPLETED)
   └─ File: chroma_client.py -> Function: index_invoice_document() -> get_embeddings()
9. Real-Time Push Notification Output
   └─ File: workers/tasks.py -> Function: _publish_sse_events() (Redis Pub/Sub)
   └─ File: routers/invoices.py -> Function: stream_invoice_status() (SSE endpoint, subscribes to the same channel)
```

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
* **API Endpoint**: `POST /api/v1/chat/sessions/{session_id}/message` (sessions created via `POST /api/v1/chat/sessions`)
* **Response Payload**: `content` (answer string), `citations` (list), and optional `generated_sql`.

```
1. API Router
   └─ File: routers/chat.py -> Function: post_chat_message()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Conversational Routing (plain Python router, not a LangGraph state machine)
   └─ File: agents/query_agent.py -> Function: run_query_agent()
      - classify_query() routes to RAG / SQL / CHAT
      - Conversation memory: last 10 messages fetched directly from Postgres via get_chat_history()
        (no LangGraph checkpointer, no token-aware trimming — see feature_6_rag.md)
4. RAG path
   └─ File: agents/query_agent.py -> calls chroma_client.query_invoice_chunks()
      - Returns top-5 chunks with no cosine-distance cutoff applied — see feature_6_rag.md
5. SQL path
   └─ File: agents/query_agent.py -> Function: execute_generated_sql()
      - Tenant isolation is enforced via a substring check (`str(tenant_id) not in sql`), not AST validation
      - Single-shot generation, no self-healing repair loop on failure — see feature_6_rag.md
6. Output Guardrails & Safety Filter
   └─ **[Not yet implemented]** No prompt-injection input filter or output data-leak filter exists in code yet.
7. LangSmith Tracing & Logging
   └─ **[Not yet implemented]** Env vars are documented in README files, but utils/llm.py never attaches a
     callback manager, so no traces are actually emitted.
```

---

## Flow 4: Audit Resolution (Approve/Reject Invoice & Dismiss Alerts)
* **API Endpoint**: `PUT /api/v1/audit/resolve/{invoice_id}`
* **Payload**: `status` (`PAID` or `REJECTED`) and `dismissed_alerts` (list of alert ids/types/messages to remove). Metadata fields (vendor, dates, amounts) are read-only in this endpoint — the UI does not send corrected values here.

```
1. API Router
   └─ File: routers/audit.py -> Function: resolve_audit_invoice()
      - Filters invoice.sa_alerts to drop entries matching dismissed_alerts (by id, type, or message)
      - Sets invoice.status to the target status
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Database Session
   └─ File: dependencies.py -> Function: get_db_session()
4. Audit Log
   └─ Writes an AuditLog row (actor_user_id, actor_role, action="RESOLVE_INVOICE", details) in the same transaction
5. Trainer Agent Feedback Loop
   └─ **[Not yet implemented]** Auditor corrections do not currently trigger agents/trainer_agent.py at all.
     Template learning only happens through the explicit /trainer/* sandbox flow (Flow 6), not automatically
     from audit resolutions. If this auto-trigger is wanted, it needs to be built — not just documented.
```

---

## Flow 5: Dashboard Analytics & Performance Metrics
* **API Endpoint**: `GET /api/v1/dashboard/metrics`

```
1. API Router
   └─ File: routers/dashboard.py -> Function: get_dashboard_metrics()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. SQL Database session aggregates
   └─ File: dependencies.py -> Function: get_db_session()
      - Aggregation is done in Python over the fetched Invoice rows, not via SQL GROUP BY
```

---

## Flow 6: Trainer Sandbox & Rules Registry (Conversational Feedback Loop)
* **API Endpoints**: `POST /api/v1/trainer/upload` (transient parse), `POST /api/v1/trainer/sessions/{session_id}/chat` (correction), `POST /api/v1/trainer/sessions/{session_id}/commit` (save rules)

```
1. API Router (Transient Upload)
   └─ File: routers/trainer.py -> Function: upload_transient_file()
      - Runs OCR + run_extraction_agent() and stores state in an in-process dict (TRAINER_SESSIONS)
      - **Known scaling gap**: this dict is not shared across replicas/workers — see feature_10_trainer.md
2. API Router (Chat Feedback)
   └─ File: routers/trainer.py -> Function: trainer_chat()
   └─ File: agents/trainer_agent.py -> Function: run_trainer_agent() -> refine_constraints()
3. API Router (Commit Rules)
   └─ File: routers/trainer.py -> Function: trainer_commit()
      - Tenant mode: saves to ExtractionTemplate table
      - Global mode: saves to config/default_templates.json
   └─ **[Not yet implemented]** Committing rules does not trigger a re-audit of existing production invoices
     for that vendor, despite this being the documented intent.
4. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
```

---

## Flow 7: Ingest from Integrations (Google Drive/Salesforce)
* **API Endpoints**: `GET /api/v1/connectors/status`, `GET /api/v1/connectors/auth-url/{provider}`, `GET /api/v1/connectors/callback/{provider}`, `GET /api/v1/connectors/files/{provider}`, `POST /api/v1/connectors/import/{provider}`

```
1. Status Check
   └─ File: routers/connectors.py -> Function: get_connectors_status()
2. Initiating Integration Auth
   └─ File: routers/connectors.py -> Function: get_auth_url()
      - Returns a hardcoded mock OAuth consent URL. No real Google/Salesforce client integration yet.
3. OAuth Callback Handler
   └─ File: routers/connectors.py -> Function: oauth_callback()
   └─ Encryption: utils/encryption.py -> Function: encrypt_token()
   └─ Database Write: adds/updates a TenantConnection record
4. Remote Folder Browsing
   └─ File: routers/connectors.py -> Function: list_connector_files()
      - Returns a hardcoded mock file list. No real Drive/Salesforce API calls yet.
   └─ Decryption: utils/encryption.py -> Function: decrypt_token()
5. Async Import Task Trigger
   └─ File: routers/connectors.py -> Function: trigger_file_import()
   └─ Celery Task Dispatch: workers/tasks.py -> Function: import_connector_file_task()
      - Uses mock/simulated file bytes rather than a real download, then calls process_invoice_task() (Flow 1)
```

**Note:** There is no `connectors/factory.py`, `connectors/google_drive.py`, or similar per-provider module — all provider logic currently lives inline in `routers/connectors.py` and is mocked. Building real OAuth2 exchanges is tracked in `feature_9_connectors.md`.
