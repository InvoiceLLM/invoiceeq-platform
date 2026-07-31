# Backend (invoice-be) Test Cases

This document details the manual/QA test suite for the FastAPI backend, reconciled against the actual implemented API surface and the real automated suite in `apps/invoice-be/tests/` (verified 2026-07-12). Earlier versions of this doc referenced endpoints that were never built or planned (`/finalize`, `/alerts/{id}/dismiss`, email-attachment ingestion, ERP export) — those have been removed. Each case below has a corresponding automated pytest, noted for reference.

## Feature 1: Multi-Tenant Authentication & Security Scoping
### TC-BE-01: Auth Fallback & Test Token Behavior
* **Goal**: Verify local-dev fallback context, `test_` token parsing, and unpaid-plan blocking.
* **How to Test**: `GET /auth/me` with (1) no header → mock Admin context, (2) `Bearer test_<uuid>_unpaid` → `402 Payment Required`.
* **Automated**: `tests/test_auth.py`

### TC-BE-02: Tenant Isolation Enforcement
* **Goal**: Ensure a tenant cannot access another tenant's invoices.
* **How to Test**: Request `GET /api/v1/invoices` with Tenant A context. Verify no Tenant B records are returned.
* **Automated**: `tests/test_queries.py::test_tenant_boundary_isolation`

---

## Feature 2: Ingestion & Storage Pipeline
### TC-BE-03: Multi-part PDF Upload & DB State Creation
* **Goal**: Verify PDF upload stores to Blob (or local fallback) and creates a database record.
* **How to Test**: POST `/api/v1/invoices/upload` with a sample PDF. Assert `batch_id`/`job_ids` in response and status `PROCESSING`.
* **⚠️ Currently failing**: this endpoint 500s on every non-duplicate upload due to a confirmed `run_in_threadpool` bug — see `docs/feature_2_pipeline.md`. Re-verify once fixed.
* **Automated**: `tests/test_ingestion.py::test_upload_single_pdf`

### TC-BE-04: Free Plan Upload Limits
* **Goal**: Block uploads if the tenant has exhausted their free invoice limit.
* **How to Test**: Set `free_invoices_remaining = 0` for a tenant. Attempt upload. Assert `402 Payment Required`.
* **Automated**: `tests/test_ingestion.py::test_free_plan_quota_exhausted`

### TC-BE-05: Duplicate Detection (Layer 1 — file hash)
* **Goal**: Verify re-uploading an identical file short-circuits to `DUPLICATE` status without enqueuing a background processing job.
* **How to Test**: Upload the same PDF bytes twice for the same tenant. Assert the second record has `status == "DUPLICATE"` and a `duplicate` alert.
* **Automated**: not yet covered by a dedicated test — recommend adding one.

---

## Feature 3: Status Tracking & Real-Time SSE Streams
### TC-BE-06: Single Status Poll
* **Goal**: Verify `GET /api/v1/invoices/status/{job_id}` returns correct DB metadata and enforces tenant isolation.
* **Automated**: `tests/test_sse.py::test_get_invoice_status`, `test_get_invoice_status_foreign_tenant`

### TC-BE-07: SSE Stream Subscription
* **Goal**: Check that the client receives real-time invoice processing updates via `GET /api/v1/invoices/stream/{batch_id}`.
* **How to Test**: Publish a message to the `invoice.update.{batch_id}` Redis channel and confirm it's yielded as an SSE frame.
* **Automated**: `tests/test_sse.py::test_sse_stream_endpoint`

### TC-BE-08: Queue Handler Status Transitions
* **Goal**: Verify the Queue Handler correctly updates PostgreSQL to `COMPLETED` on success and `AUDIT_REQUIRED` (with alerts) on validation failure.
* **Automated**: `tests/test_sse.py::test_queue_worker_updates_database`, `test_queue_worker_audit_anomalies`. Fixed 2026-07-27: the whole file previously failed to collect at all (`ModuleNotFoundError`) due to a stale `from workers.tasks import process_invoice_task` import (`workers.tasks` was deleted during the legacy task-queue migration); repointed at `queue_worker.handlers.handle_process_invoice` and renamed both tests off their leftover naming.

---

## Feature 4: Invoice Queries & PDF Delivery API
### TC-BE-09: Fetch Invoice List with Filters
* **Goal**: Verify pagination, date range, status, and tag filters on `GET /api/v1/invoices`.
* **Automated**: `tests/test_queries.py::test_get_invoices_list_and_filters`

### TC-BE-10: Single Invoice Detail
* **Goal**: Verify `GET /api/v1/invoices/{invoice_id}` returns full record detail.
* **Automated**: `tests/test_queries.py::test_get_single_invoice_detail`

### TC-BE-11: Secure PDF Delivery
* **Goal**: Retrieve the original invoice PDF via `GET /api/v1/invoices/{invoice_id}/pdf`.
* **How to Test**: Assert `Content-Type: application/pdf` and a valid inline stream.
* **Automated**: `tests/test_queries.py::test_stream_pdf`

---

## Feature 5: Multi-Modal Extraction & Verification Agent
### TC-BE-12: Successful Extraction Pipeline
* **Goal**: Verify structured extraction populates all `Invoice` columns and sets `status = COMPLETED` when math checks pass.
* **Automated**: `tests/test_extraction.py::test_successful_extraction_pipeline`

### TC-BE-13: Mathematical Discrepancy Flagging
* **Goal**: Mark invoices `AUDIT_REQUIRED` with an alert when line-item/tax math doesn't reconcile.
* **Automated**: `tests/test_extraction.py::test_verify_line_items_and_totals_math`

### TC-BE-14: Token Guardrail Pre-Flight Block
* **Goal**: Verify oversized prompts are blocked before an LLM call, with a `token_limit_exceeded` alert.
* **Automated**: `tests/test_extraction.py::test_token_guardrails_limit_exceeded`

---

## Feature 6: Conversational RAG & Thread Management
### TC-BE-15: Session Lifecycle & Tenant Isolation
* **Goal**: Create/list/retrieve chat sessions; verify a foreign tenant gets `403` on `GET /api/v1/chat/sessions/{session_id}`.
* **Automated**: `tests/test_rag.py::test_session_lifecycle_and_tenant_isolation`

### TC-BE-16: Message Routing & History Persistence
* **Goal**: Posting to `POST /api/v1/chat/sessions/{session_id}/message` runs the router agent and persists both turns.
* **Automated**: `tests/test_rag.py::test_chat_message_routing_and_history_saving`

### TC-BE-17: SQL Guardrail Enforcement
* **Goal**: Verify mutating SQL and cross-tenant queries are rejected before execution.
* **Note**: current implementation checks tenant isolation via a substring match on the UUID, which is weaker than true predicate validation — see `docs/feature_6_rag.md` Task 6.6 for the hardening recommendation. This test only covers the happy-path/obvious-reject cases, not a deliberate bypass attempt.
* **Automated**: `tests/test_rag.py::test_sql_guardrail_safety_enforcement`

### TC-BE-18: Vector Metadata Tenant Isolation
* **Goal**: Confirm ChromaDB indexing/query strictly isolates chunks by `tenant_id`.
* **Automated**: `tests/test_rag.py::test_vector_metadata_tenant_isolation`

---

## Feature 7: Audit Resolution & Finalization
### TC-BE-19: Resolve to PAID / REJECTED
* **Goal**: Verify `PUT /api/v1/audit/resolve/{invoice_id}` updates status and dismisses alerts (both string and dict alert formats).
* **Automated**: `tests/test_audit.py::test_resolve_invoice_paid`, `test_resolve_invoice_rejected_dict_alerts`

### TC-BE-20: Invalid Status Rejection & Tenant Isolation
* **Goal**: Verify an invalid target status returns `400`, and cross-tenant resolution attempts are blocked.
* **Automated**: `tests/test_audit.py::test_resolve_invalid_status`, `test_resolve_tenant_isolation`

---

## Feature 8: Dashboard Metrics & Analytics API
### TC-BE-21: Aggregate Metrics Math
* **Goal**: Verify `total_invoiced`, `paid_amount`, `outstanding_amount`, `at_risk_amount` compute correctly across a mixed-status invoice set.
* **Automated**: `tests/test_dashboard.py::test_aggregate_metrics`

### TC-BE-22: Metrics Filters
* **Goal**: Verify date/vendor/status filters correctly scope the aggregation.
* **Automated**: `tests/test_dashboard.py::test_metrics_filters`

---

## Feature 9: Third-Party Connectors & Ingestion
### TC-BE-23: Connector Status & Encryption
* **Goal**: Verify `GET /api/v1/connectors/status` reflects `Not Configured`/`Active` correctly, and that stored tokens round-trip through AES-256 Fernet encryption.
* **Automated**: `tests/test_connectors.py::test_connectors_status_not_configured`, `test_connectors_status_active`, `test_encryption_decryption`

### TC-BE-24: OAuth Flow (currently mocked, not real provider calls)
* **Goal**: Verify auth-URL generation, callback token exchange, and file listing endpoints work end-to-end against mock provider responses.
* **Automated**: `tests/test_connectors.py::test_get_auth_url`, `test_oauth_callback`, `test_list_files`

### TC-BE-25: Background Import Dispatch
* **Goal**: Verify `POST /api/v1/connectors/import/{provider}` queues the Storage Queue import message.
* **Automated**: `tests/test_connectors.py::test_trigger_import`

---

## Feature 10: AI Trainer Sandbox & Rules Registry
### TC-BE-27: Transient Session Flow
* **Goal**: Upload → correct via chat → commit, without ever writing to the permanent `invoices` table until commit.
* **Automated**: `tests/test_trainer.py::test_trainer_flow`

### TC-BE-28: Rule Commit Persistence
* **Goal**: Verify committed rules are saved to `ExtractionTemplate` (tenant mode) correctly.
* **Automated**: `tests/test_trainer.py::test_trainer_commit_db`

---

## Feature 11: Billing & Plan Limits
### TC-BE-29: Block Unpaid Tenant Accounts
* **Goal**: Block all API access for tenants marked `unpaid`.
* **Automated**: `tests/test_auth.py::test_auth_me_unpaid_payment_required`

### TC-BE-30: PayU Checkout & Callbacks
* **Goal**: Not testable yet — `routers/billing.py` does not exist in code despite `feature_11_billing.md` describing it. No automated coverage possible until the router is built.
