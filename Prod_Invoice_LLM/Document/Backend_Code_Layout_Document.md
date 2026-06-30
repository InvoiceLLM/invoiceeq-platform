# API Flow Directory & Code Mapping

This document maps each system API to its sequential file and function execution path.

---

## Flow 1: Ingest & Extract Invoice (Async Pipeline)
* **API Endpoints**: `POST /api/v1/invoices/upload` (Upload) & `GET /api/v1/invoices/stream/{batch_id}` (SSE status stream)

```
1. API Router
   └─ File: routers/invoices.py -> Function: upload_invoice()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Async Task Queue (Dispatched)
   └─ File: workers/tasks.py -> Function: process_invoice_task()
4. Multi-Modal Text, Visual Parsing & Verification
   └─ File: agents/extraction_agent.py -> Class: ExtractionAgent -> Function: run()
5. Offset & Template Coordinate Lookups (Agent Tool)
   └─ File: agents/extraction_agent.py -> Function: fetch_template_rules_tool()
6. Validation checks (Agent Tool)
   └─ File: agents/extraction_agent.py -> Function: validate_extracted_schema()
7. Calculation Validation (Extraction Tool)
   └─ File: agents/extraction_agent.py -> Function: validate_math_totals()
8. Local Vector Calculation & Storage
   └─ File: chroma_client.py -> Function: add_documents_to_collection()
9. Sentence Transformer Processing
   └─ File: chroma_client.py -> Function: calculate_embeddings()
10. Real-Time Push Notification Output
    └─ File: routers/invoices.py -> Function: stream_batch_events()
```

---

## Flow 2: Poll Single Invoice Ingestion Status (Sync Polling)
* **API Endpoint**: `GET /api/v1/invoices/status/{job_id}`

```
1. API Router
   └─ File: routers/invoices.py -> Function: poll_invoice_status()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Database Query
   └─ File: dependencies.py -> Function: get_db_session()
```

---

## Flow 3: Semantic Chat & Invoice Query
* **API Endpoint**: `POST /api/v1/chat/query`
* **Response Payload**: Contains conversational `answer` string, list of `citations` page mappings, and the optional `generated_sql` query code for database auditability.

```
1. API Router
   └─ File: routers/chat.py -> Function: query_invoices_chat()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Conversational RAG Loop Execution (Stateful Checkpointer Memory)
   └─ File: agents/query_agent.py -> Class: QueryAgent -> Function: run()
      - Uses LangGraph checkpointer `InMemorySaver()` to persist conversation history context
4. Local Search Execution (Query Agent Tool)
   └─ File: agents/query_agent.py -> Function: query_chroma_vector_store()
5. Local Embeddings Calculation
   └─ File: chroma_client.py -> Function: calculate_embeddings()
6. Vector DB Cosine Distance Filter
   └─ File: chroma_client.py -> Function: query_semantic_chunks()
7. Database Aggregates Lookup (Query Agent Tool)
   └─ File: agents/query_agent.py -> Function: query_postgresql_aggregates()
8. Output Guardrails & Safety Filter
   - Enforces output check rules to prevent data leaks or bad database syntax
9. LangSmith Tracing & Logging
   - Automatically tracks token costs, latency, and agent step decisions in real-time
```

---

## Flow 4: Audit Resolution (Approve/Reject/Pay Invoice & Dismiss Alerts)
* **API Endpoint**: `PUT /api/v1/audit/resolve/{invoice_id}`
* **Payload**: Form values, remaining active/dismissed `alerts` list, and target final status (`PAID` or `REJECTED`).

```
1. API Router
   └─ File: routers/audit.py -> Function: resolve_audit_invoice()
      ```python
      # Proposed implementation logic outline inside resolve_audit_invoice():
      #
      # @router.put("/resolve/{invoice_id}")
      # def resolve_audit_invoice(invoice_id: UUID, payload: AuditResolutionPayload, db: Session, current_user: User):
      #     # 1. Retrieve the target invoice
      #     invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
      #
      #     # 2. Save manual corrections (metadata overrides)
      #     invoice.amount = payload.amount
      #     invoice.vendor_name = payload.vendor_name
      #     invoice.invoice_date = payload.invoice_date
      #
      #     # 3. Handle alert dismissals / resolution
      #     # Since alerts are stored inline inside the invoices table as a JSONB array,
      #     # we update the alerts list directly on the invoice record.
      #     invoice.alerts = [alert for alert in invoice.alerts if alert['id'] not in payload.dismissed_alerts_list]
      #
      #     # 4. Resolve the status (stamps PAID or REJECTED)
      #     invoice.status = payload.status
      #
      #     # 5. Save audit metadata logging (auditor details & timestamp)
      #     audit_log = AuditLog(
      #         invoice_id=invoice.id,
      #         changed_by=current_user.id,
      #         action="audit_resolution",
      #         previous_state=old_state_json,
      #         new_state=new_state_json
      #     )
      #     db.add(audit_log)
      #     db.commit()
      ```
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Database Session Verification
   └─ File: dependencies.py -> Function: get_db_session()
      - Updates PostgreSQL invoice record (saves corrected fields, clears/updates `alerts` array, set status to PAID or REJECTED)
4. Verification Feedback trigger (Spawns Trainer Agent Optimization)
   └─ File: agents/trainer_agent.py -> Class: TrainerAgent -> Function: run()
5. Template optimization generation (Trainer Tool)
   └─ File: agents/trainer_agent.py -> Function: analyze_corrections_diff()
6. Template persistence
   └─ File: agents/trainer_agent.py -> Function: save_override_template_rules()
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
```

---

## Flow 6: Trainer Rules & Chat Management (Conversational Feedback Loop)
* **API Endpoints**: `POST /api/v1/trainer/chat` (Chat Feedback) & `POST /api/v1/trainer/rules` (Commit to Registry)

```
1. API Router (Chat Feedback)
   └─ File: routers/trainer.py -> Function: submit_trainer_chat_feedback()
      - Converts natural language rules into structured JSON constraints via LLM
      - Returns updated extraction preview results to the frontend
2. API Router (Commit Rules)
   └─ File: routers/trainer.py -> Function: commit_trainer_rules_registry()
      - Saves the finalized structured templates in PostgreSQL under #VendorName
3. Authentication & Tenant Scope (Requires 'Admin' or 'Auditor' Persona check)
   └─ File: dependencies.py -> Function: get_tenant_context()
4. Save rules to database
   └─ File: dependencies.py -> Function: get_db_session()
```

---

## Flow 7: Ingest from Integrations (Google Shared Drive/Salesforce)
* **API Endpoints**: `GET /api/v1/connectors/auth-url/{provider}`, `GET /api/v1/connectors/callback/{provider}`, `GET /api/v1/connectors/files/{provider}`, & `POST /api/v1/connectors/import/{provider}`

```
1. Initiating Integration Auth
   ├─ API Router: routers/connectors.py -> Function: get_auth_url()
   └─ Controller: connectors/factory.py -> Class: ConnectorFactory -> get_auth_url()
2. OAuth Callback Handler
   ├─ API Router: routers/connectors.py -> Function: handle_oauth_callback()
   ├─ Token Exchange: connectors/google_drive.py -> Function: exchange_code_for_tokens()
   ├─ Encryption: dependencies.py -> Function: encrypt_token_value() (using TOKEN_ENCRYPTION_KEY)
   └─ Database Write: dependencies.py -> Function: get_db_session() (adds TenantConnection record)
3. Remote Folder Browsing
   ├─ API Router: routers/connectors.py -> Function: list_remote_files()
   ├─ Decryption: dependencies.py -> Function: decrypt_token_value() (loads TOKEN_ENCRYPTION_KEY)
   ├─ Auth Refresh: connectors/google_drive.py -> Function: refresh_access_token() (if expired)
   └─ Fetch Remote Index: connectors/google_drive.py -> Function: list_files() (requests remote folder API)
4. Async Import Task Trigger
   ├─ API Router: routers/connectors.py -> Function: trigger_remote_import() (accepts selected file list)
   ├─ Celery Task Dispatch: workers/tasks.py -> Function: process_remote_import_task()
   ├─ Background File Download: connectors/google_drive.py -> Function: download_file()
   ├─ File Storage: workers/tasks.py -> Uploads downloaded binary to Azure Blob Storage
   └─ Process Ingestion: workers/tasks.py -> Triggers process_invoice_task() (Flow 1 ingestion)
```

