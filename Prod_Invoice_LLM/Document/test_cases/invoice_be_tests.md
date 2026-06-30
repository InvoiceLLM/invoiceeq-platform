# Backend (invoice-be) Test Cases

This document details the test suite for the FastAPI backend components.

## Feature 1: Multi-Tenant Authentication & Security Scoping
### TC-BE-01: JWT Decoding & Authentication Verification
* **Goal**: Verify that requests without a JWT or with an invalid JWT are rejected.
* **How to Test**: Send GET to `/api/v1/invoices` with (1) no header, (2) invalid JWT. Assert `401 Unauthorized`.

### TC-BE-02: Tenant Isolation Enforcement
* **Goal**: Ensure user cannot access data of other tenants.
* **How to Test**: Request invoice list with Tenant A credentials. Verify no invoices from Tenant B are returned.

---

## Feature 2: Ingestion & Storage Pipeline
### TC-BE-03: Multi-part PDF Upload & DB State Creation
* **Goal**: Verify PDF upload stores to Azure and creates a database record.
* **How to Test**: POST `/api/v1/invoices/upload` with a sample PDF. Assert storage upload, status `PROCESSING`, and batch ID in response.

### TC-BE-04: Free Plan Upload Limits
* **Goal**: Block uploads if the tenant has exhausted their free invoice limit.
* **How to Test**: Mock `free_invoices_remaining = 0` for a tenant. Attempt upload. Assert `402 Payment Required`.

---

## Feature 3: Status Tracking & Real-Time SSE Streams
### TC-BE-05: Server-Sent Events (SSE) Stream Subscription
* **Goal**: Check that the client receives real-time invoice processing updates.
* **How to Test**: Connect to `/api/v1/invoices/stream?tenant_id=XYZ`. Trigger upload, assert event updates are pushed.

### TC-BE-06: SSE Disconnection Handling
* **Goal**: Verify that resource cleanup happens when the client closes connection.
* **How to Test**: Open SSE stream and close immediately. Verify backend releases the connection and active threads.

---

## Feature 4: Invoice Queries & PDF Delivery API
### TC-BE-07: Fetch Invoice List with Filters
* **Goal**: Verify retrieval of invoice records by status, vendor, and tags.
* **How to Test**: GET `/api/v1/invoices?status=AUDIT_REQUIRED`. Assert all records match query filter.

### TC-BE-08: Secure PDF Download Endpoint
* **Goal**: Retrieve the original invoice PDF securely from Azure Blob storage.
* **How to Test**: GET `/api/v1/invoices/{id}/download`. Assert `Content-Type: application/pdf` and valid file stream.

---

## Feature 5: Multi-Modal Extraction & Verification Agent
### TC-BE-09: LangGraph Agent Coordinate Mapping
* **Goal**: Verify coordinates and values are extracted correctly from a layout.
* **How to Test**: Run `process_invoice_task` on a sample PDF. Assert `invoice_number` and bounding box coordinate keys are populated.

### TC-BE-10: Mathematical Discrepancy Flagging
* **Goal**: Mark invoices as `AUDIT_REQUIRED` if arithmetic checks fail.
* **How to Test**: Process a mock invoice with `subtotal = 100`, `tax = 10`, `total = 115`. Verify database status is set to `AUDIT_REQUIRED` and alert record is written.

---

## Feature 6: Conversational RAG & Thread Management
### TC-BE-11: RAG Session Creation and Prompt Processing
* **Goal**: Ask invoice questions and get validated answers.
* **How to Test**: POST `/api/v1/chat/sessions/{session_id}/query` with question *"Who is the vendor?"*. Assert correct textual response and reference citations.

### TC-BE-12: SQL Execution Inspection
* **Goal**: Verify SQL translation from natural language is included in chat output.
* **How to Test**: Submit query *"Show total amount spent"*. Assert returned payload includes executable SQL statement.

---

## Feature 7: Audit Resolution & Finalization
### TC-BE-13: Warning Dismissal Action
* **Goal**: Verify dismissals clear alerts from JSONB database column.
* **How to Test**: POST `/api/v1/invoices/{id}/alerts/{alert_id}/dismiss`. Verify alert array is updated in database.

### TC-BE-14: Invoice State Finalization
* **Goal**: Allow finalized invoices to be marked as `COMPLETED`.
* **How to Test**: POST `/api/v1/invoices/{id}/finalize`. Verify state updates to `COMPLETED` and is locked from further edits.

---

## Feature 8: Dashboard Metrics & Analytics API
### TC-BE-15: Spend Analytics Retrieval
* **Goal**: Verify total spend, tax, and invoice counts aggregate correctly.
* **How to Test**: GET `/api/v1/dashboard/metrics`. Assert returned values sum matching DB records.

### TC-BE-16: Trend Time-Series Graph Data
* **Goal**: Get weekly/monthly count and volume breakdown.
* **How to Test**: GET `/api/v1/dashboard/trends?range=30d`. Assert dates are sorted chronologically.

---

## Feature 9: Third-Party Connectors & Ingestion
### TC-BE-17: Email Attachment Ingestion Service
* **Goal**: Poll mailbox, extract PDF attachment, and route to ingestion pipeline.
* **How to Test**: Run connector cron job with test email containing invoice. Assert PDF is ingested and database record is created.

### TC-BE-18: ERP Export Connector Trigger
* **Goal**: Push finalized invoices to mock ERP endpoint.
* **How to Test**: POST `/api/v1/connectors/erp/export` for invoice. Assert payload structure matches integration spec.

---

## Feature 10: AI Trainer Sandbox & Rules Registry
### TC-BE-19: Transient Invoice Upload
* **Goal**: Process PDF layout immediately without committing to main invoices table.
* **How to Test**: POST `/api/v1/trainer/upload` with PDF. Assert session ID and parsed key-values are returned, but database remains untouched.

### TC-BE-20: Rule Commit & Template Registry
* **Goal**: Save extraction templates after training corrections.
* **How to Test**: POST `/api/v1/trainer/sessions/{id}/commit`. Assert template row is created in `extraction_templates` table.

---

## Feature 11: Billing & Plan Limits
### TC-BE-21: Block Unpaid Tenant Accounts
* **Goal**: Block accounts marked as unpaid.
* **How to Test**: Set tenant subscription status to `'unpaid'`. Try requesting invoices. Assert `402 Payment Required`.

### TC-BE-22: Usage Quota Enforcement
* **Goal**: Verify limits for paid tiers.
* **How to Test**: Exhaust paid tier limits. Verify upload is blocked.
