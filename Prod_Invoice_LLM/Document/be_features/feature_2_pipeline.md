# Feature 2: Ingestion & Storage Pipeline

Accept PDF uploads, persist them to Azure Blob Storage, and queue background tasks for metadata extraction.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py)
* Database Models: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)
* Background Worker: [apps/invoice-be/workers/tasks.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/workers/tasks.py)

### Tasks
- [x] **Task 2.1: Implement Ingestion Router Endpoint**
  - Implement `POST /api/v1/invoices/upload` accepting single/multiple PDF files.
  - Generate a unique `batch_id` for each session.
  - Configure the route parameter to accept an optional `tags` array parameter from the form.
- [x] **Task 2.2: Persist Files to Azure Blob Storage**
  - Initialize the Azure Blob Storage client from credentials.
  - Upload the raw binary stream to a tenant-isolated storage container folder structure: `tenants/{tenant_id}/invoices/{invoice_id}.pdf`.
- [x] **Task 2.3: Create Processing DB Entry**
  - Insert a record into the `invoices` table with status `PROCESSING` and the associated tags payload.
  - Return the generated `batch_id` and the database `job_ids` in the HTTP response.
- [x] **Task 2.4: Dispatch Celery Extraction Task**
  - Enqueue the extraction job `process_invoice_task` in the Celery queue.
  - Pass parameter identifiers: `batch_id`, `file_path`, and `tenant_id`.
- [x] **Task 2.5: Enforce Free Plan 50 Invoice limit**
  - Check the tenant's remaining invoices before creating records. If `billing_plan == 'free'` and `free_invoices_remaining <= 0`, raise `HTTPException(402, "Limit reached")`.
  - Decrement the count `free_invoices_remaining = free_invoices_remaining - 1` upon successful upload.
- [x] **Task 2.6: Update SQLModel Schema with Optional Columns**
  - Update `models.py` class `Invoice` to define new optional fields: `invoice_number: str | None = Field(default=None)`, `invoice_date: date | None = Field(default=None)`, `due_date: date | None = Field(default=None)`, `tax_amount: float | None = Field(default=None)`, `po_number: str | None = Field(default=None)`, `tags: list | None = Field(default=[], sa_column=Column(JSONB))`, and `items: list | None = Field(default=[], sa_column=Column(JSONB))`.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_ingestion.py` testing file uploads.
* **Manual Verification**: Run `docker compose up -d` to spin up local Redis/Postgres/ChromaDB. Upload a mock PDF to the router and check that the Celery task receives it.
