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
4. Multi-Modal Text & Visual Parsing
   └─ File: agents/extraction_agent.py -> Class: ExtractionAgent -> Function: run()
5. Offset & Template Coordinate Lookups (Agent Tool)
   └─ File: agents/extraction_agent.py -> Function: fetch_template_rules_tool()
6. Validation checks (Agent Tool)
   └─ File: agents/extraction_agent.py -> Function: validate_extracted_schema()
7. Math and Vendor Registry Checks
   └─ File: agents/verification_agent.py -> Class: VerificationAgent -> Function: run()
8. Calculation Validation (Verification Tool)
   └─ File: agents/verification_agent.py -> Function: validate_math_totals()
9. Supplier Approval Match (Verification Tool)
   └─ File: agents/verification_agent.py -> Function: match_vendor_registry()
10. Local Vector Calculation & Storage
    └─ File: chroma_client.py -> Function: add_documents_to_collection()
11. Sentence Transformer Processing
    └─ File: chroma_client.py -> Function: calculate_embeddings()
12. Real-Time Push Notification Output
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

```
1. API Router
   └─ File: routers/chat.py -> Function: query_invoices_chat()
2. Authentication & Tenant Scope
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Conversational RAG Loop Execution
   └─ File: agents/query_agent.py -> Class: QueryAgent -> Function: run()
4. Local Search Execution (Query Agent Tool)
   └─ File: agents/query_agent.py -> Function: query_chroma_vector_store()
5. Local Embeddings Calculation
   └─ File: chroma_client.py -> Function: calculate_embeddings()
6. Vector DB Cosine Distance Filter
   └─ File: chroma_client.py -> Function: query_semantic_chunks()
7. Database Aggregates Lookup (Query Agent Tool)
   └─ File: agents/query_agent.py -> Function: query_postgresql_aggregates()
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
      #     for alert_id in payload.dismissed_alerts_list:
      #         alert = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
      #         if alert:
      #             alert.is_dismissed = True
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
