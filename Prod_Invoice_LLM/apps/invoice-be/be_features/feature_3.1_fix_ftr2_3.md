# Feature 3.1: Duplicate Detection & Ingestion UI Refinements

Integrate duplicate invoice detection checks, background processing bypass for identical uploads, and status ledger display improvements for cleaner layout density.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py) → `POST /invoices/upload` → `upload_invoices()`
* Database Models: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)
* Recent Invoices Table Component: [apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx) → `getStatusBadge()`

### Functionality
Inside `upload_invoices()`, per file: compute `hashlib.sha256(file_bytes).hexdigest()`, then `select(Invoice).where(tenant_id, file_hash == ...)`. On a hit, it builds a new `Invoice` row copying every extracted field from the existing match, sets `status="DUPLICATE"`, appends a `duplicate` alert, and publishes a synthetic `DUPLICATE` SSE event directly via `redis.Redis.from_url(...).publish()` (a raw sync client constructed inline, not the async one `sse_event_generator()` uses) — then `continue`s the loop without touching Blob Storage or Azure Storage Queues. On a miss, it proceeds to the normal upload path (Task 2.18's P0 bug lives right after this branch, in `feature_2_pipeline_extraction.md`).

### Tasks
- [x] **Task 3.1.1: Add file_hash field to DB Model**
  - Add `file_hash` column to the `Invoice` schema.
  - Generate and apply Alembic migration revisions.
- [x] **Task 3.1.2: Check Duplicate File Signatures in API**
  - In `POST /api/v1/invoices/upload`, compute the SHA-256 hash of each uploaded file's binary stream.
  - Check the database for duplicate hashes matching the current tenant.
  - If a duplicate is found:
    - Set the status of the new invoice row to `DUPLICATE`.
    - Clone the extraction data fields (`vendor_name`, `grand_total`, `tax_amount`, `po_number`, `invoice_number`, `invoice_date`, `due_date`, `items`, `tags`) from the existing database record.
    - Insert a warning alert in `sa_alerts`: `[{"type": "duplicate", "message": "This file is a duplicate of a previously uploaded invoice."}]`.
    - Emit an SSE duplicate event on the batch's stream so connected clients see the duplicate resolution in real time.
    - Do not dispatch a Storage Queue extraction message.
- [x] **Task 3.1.3: Update UI RecentInvoicesTable Component**
  - Verified done in `components/dashboard/RecentInvoicesTable.tsx`: `getStatusBadge()` renders a `Duplicate` badge (amber, with a `title` tooltip) for `status === "DUPLICATE"`; the vendor cell falls back to `"Processing Vendor..."` only while `status === "PROCESSING"` and `"Unknown Vendor"` otherwise; the tags row uses `opacity-0 max-h-0` → `group-hover:opacity-100 group-hover:max-h-16` with a `transition-all duration-300` to fade/slide in only on row hover.
- [ ] **Task 3.1.4: Layer 2 duplicate detection (post-extraction)**
  - After extraction completes, check for an existing invoice with the same `invoice_number` + `vendor_name` for the tenant, catching re-scanned/re-named duplicates that Layer 1's file-hash check misses because the underlying bytes differ.

### Verification Plan
* **Manual Verification**:
  - Ingest the same invoice PDF twice on the `/ingestion` portal.
  - Verify that the second document is parsed instantly, avoiding Storage Queue dispatch.
  - Verify that the second item has the status `Duplicate` with a hover message.
  - Verify that the row tags list only appears upon hovering over the table row.
