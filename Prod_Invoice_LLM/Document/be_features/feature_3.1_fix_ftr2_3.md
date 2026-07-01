# Feature 3.1: Duplicate Detection & Ingestion UI Refinements

Integrate duplicate invoice detection checks, background processing bypass for identical uploads, and status ledger display improvements for cleaner layout density.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py)
* Database Models: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)
* Recent Invoices Table Component: [apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx)

### Tasks
- [ ] **Task 3.1.1: Add file_hash field to DB Model**
  - Add `file_hash` column to the `Invoice` schema.
  - Generate and apply Alembic migration revisions.
- [ ] **Task 3.1.2: Check Duplicate File Signatures in API**
  - In `POST /api/v1/invoices/upload`, compute the SHA-256 hash of each uploaded file's binary stream.
  - Check the database for duplicate hashes matching the current tenant.
  - If a duplicate is found:
    - Set the status of the new invoice row to `DUPLICATE`.
    - Clone the extraction data fields (`vendor_name`, `grand_total`, `tax_amount`, `po_number`, `invoice_number`, `invoice_date`, `due_date`, `items`, `tags`) from the existing database record.
    - Insert a warning alert in `sa_alerts`: `[{"type": "duplicate", "message": "This file is a duplicate of a previously uploaded invoice."}]`.
    - Do not dispatch a Celery extraction task.
- [ ] **Task 3.1.3: Update UI RecentInvoicesTable Component**
  - Add a custom `Duplicate` status badge handling for `status === "DUPLICATE"`, featuring a hover tooltip displaying the warning message.
  - Fix the client / vendor name logic:
    - Display `"Processing Vendor..."` only when status is `"PROCESSING"`.
    - Fallback to `"Unknown Vendor"` instead of `"Processing Vendor..."` if the invoice status is completed but no vendor name could be parsed.
  - Update CSS rules on the `#tags` list row element to be hidden by default (zero height and opacity) and smoothly fade/slide in only when the containing row is hovered (`group-hover:` triggers).

### Verification Plan
* **Manual Verification**:
  - Ingest the same invoice PDF twice on the `/ingestion` portal.
  - Verify that the second document is parsed instantly, avoiding Celery dispatch.
  - Verify that the second item has the status `Duplicate` with a hover message.
  - Verify that the row tags list only appears upon hovering over the table row.
