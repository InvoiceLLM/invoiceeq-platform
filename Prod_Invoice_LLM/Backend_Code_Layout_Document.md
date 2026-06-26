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

## Flow 6: Trainer Rules Management (Manual rules insertion)
* **API Endpoint**: `POST /api/v1/trainer/rules`

```
1. API Router
   └─ File: routers/trainer.py -> Function: create_extraction_rules()
2. Authentication & Tenant Scope (Requires 'Admin' Role check)
   └─ File: dependencies.py -> Function: get_tenant_context()
3. Save rules to database
   └─ File: dependencies.py -> Function: get_db_session()
```
