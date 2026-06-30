# Backend API Gaps & Discrepancies Scratchpad

This scratchpad records all missing or redundant backend features/APIs identified during the review of the frontend screens. We will use this to reconcile the backend tasks after analyzing all screens.

## Identified Gaps (Missing Backend APIs)

### Screen 1: Dashboard (Command Center)
- **`GET /api/v1/invoices`**: Required to fetch the paginated list of invoices for the "Recent Invoices" table, with support for search and tenant filters.
- **`GET /api/v1/connectors/status`**: Required to check the connection status (`Active` / `Inactive`) of Salesforce, SAP, QuickBooks, and Webhooks for the sidebar panel.
- **`GET /api/v1/dashboard/metrics` Schema Update**: Ensure payload structure explicitly returns properties for total spend, outstanding spend, paid ratios, at-risk values, temporal data (trendline charts), and vendor groupings.

### Screen: Ingestion Loader
- **Tag Integration**: Update `POST /api/v1/invoices/upload` to accept a `tags: list[str]` parameter.
- **SSE Warning Flags**: Update Celery task results and SSE streaming to pass the `alerts` array payload when status transitions to `AUDIT_REQUIRED`.

### Screen: Auditor Tab (Review)
- **`GET /api/v1/invoices/{invoice_id}`**: Required to fetch a single invoice's extracted metadata and coordinates to populate the form fields.
- **`GET /api/v1/invoices/{invoice_id}/pdf`**: Required to stream the secure PDF file or provide a secure Azure SAS URL to render the document in `react-pdf`.
- **Alert Dismissals**: Simplify `PUT /api/v1/audit/resolve/{invoice_id}` to only handle warning array removals and status updates (`PAID` / `REJECTED`). Form fields are read-only.

### Screen: Semantic Chat Assistant
- **`GET /api/v1/chat/sessions`**: Lists all active conversation threads for the tenant.
- **`POST /api/v1/chat/sessions`**: Creates a new session (returning a unique `session_id`).
- **`GET /api/v1/chat/sessions/{session_id}`**: Retrieves message history for a chosen thread.
- **`POST /api/v1/chat/sessions/{session_id}/query`**: Handles messaging inside session scopes.

### Screen: Trainer Console
- **`POST /api/v1/trainer/upload`**: Temporary upload endpoint that parses the PDF but does not save the invoice to the DB or Azure Storage long-term.
- **`POST /api/v1/trainer/sessions/{session_id}/chat`**: Conversational adjustment Q&A endpoint.
- **`POST /api/v1/trainer/sessions/{session_id}/commit`**: Commits the adjusted rules or prompt parameters to the `extraction_templates` table in PostgreSQL under the vendor's name.

### Billing & Subscription Integrations (Marketing Website)
- **`POST /api/v1/billing/create-checkout-session`**: Triggers Stripe Checkout page redirects for monthly Pro Price IDs.
- **`POST /api/v1/webhooks/stripe`**: Handles Stripe payments callbacks, upgrading accounts to `pro` or locking them to `unpaid` when monthly charges fail.
- **50 Invoices Quota check**: Implemented in `/upload` endpoints to raise `402 Payment Required` if the quota is exhausted on the `free` plan.
