# Feature 4: Invoice Queries & PDF Delivery API

Expose query endpoints for pagination, list filters, and safe PDF document delivery to the client.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py) → `GET /invoices` → `list_invoices()`, `GET /invoices/{id}` → `get_invoice()`, `GET /invoices/{id}/pdf` → `get_invoice_pdf()`
* Storage Helper: [apps/invoice-be/services/storage.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/services/storage.py) → `download_pdf_from_storage()`

### Functionality
`list_invoices()` builds one `select(Invoice).where(tenant_id == ...)` query, optionally chaining `.where()` clauses for `start_date`/`end_date`/`status`/`tag`, then `.offset(offset).limit(limit)` (default page size 10, capped at 100). Tag filtering branches on DB dialect: Postgres uses a JSONB `.contains([tag])`, everything else (e.g. SQLite in tests) falls back to a `LIKE` string match on the raw column. `get_invoice()` is the same tenant-scoped lookup by primary key. `get_invoice_pdf()` re-fetches the invoice for tenant isolation, calls `services/storage.py::download_pdf_from_storage(invoice.file_path)`, and streams the bytes back as `application/pdf` with `Content-Disposition: inline` — the browser never gets a direct Azure Blob URL or credential.

### Tasks
- [x] **Task 4.1: Code paginated Invoices List Route**
  - Implement `GET /api/v1/invoices` fetching a list of matching records.
  - Enforce pagination offsets, date ranges, status filters, and search tags.
  - Limit returned datasets strictly to the requesting `tenant_id`.
- [x] **Task 4.2: Code Single Invoice Fetch Route**
  - Implement `GET /api/v1/invoices/{invoice_id}` returning full DB columns (such as alerts list, totals, PO numbers, and vendor name).
- [x] **Task 4.3: Create Secure PDF Delivery Route**
  - Implement `GET /api/v1/invoices/{invoice_id}/pdf` to stream the PDF file.
  - Fetch the file binary from Azure Blob Storage and return it as `application/pdf` inline stream, preventing exposure of raw Azure storage credentials to the browser.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_queries.py` checking pagination and tenant boundary filters.
* **Manual Verification**: Request an invoice PDF via the API and ensure it loads inline in a standard browser PDF preview canvas.
