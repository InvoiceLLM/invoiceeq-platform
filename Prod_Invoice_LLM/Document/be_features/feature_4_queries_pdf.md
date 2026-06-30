# Feature 4: Invoice Queries & PDF Delivery API

Expose query endpoints for pagination, list filters, and safe PDF document delivery to the client.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py)

### Tasks
- [ ] **Task 4.1: Code paginated Invoices List Route**
  - Implement `GET /api/v1/invoices` fetching a list of matching records.
  - Enforce pagination offsets, date ranges, status filters, and search tags.
  - Limit returned datasets strictly to the requesting `tenant_id`.
- [ ] **Task 4.2: Code Single Invoice Fetch Route**
  - Implement `GET /api/v1/invoices/{invoice_id}` returning full DB columns (such as alerts list, totals, PO numbers, and vendor name).
- [ ] **Task 4.3: Create Secure PDF Delivery Route**
  - Implement `GET /api/v1/invoices/{invoice_id}/pdf` to stream the PDF file.
  - Fetch the file binary from Azure Blob Storage and return it as `application/pdf` inline stream, preventing exposure of raw Azure storage credentials to the browser.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_queries.py` checking pagination and tenant boundary filters.
* **Manual Verification**: Request an invoice PDF via the API and ensure it loads inline in a standard browser PDF preview canvas.
