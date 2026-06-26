# Database Schema Document

This document defines the storage layers for the **Invoice AI SaaS Platform**. The platform uses a hybrid storage model:
1. **Azure Database for PostgreSQL (Flexible Server)**: For structured relational data, transactions, and audit records.
2. **ChromaDB**: For unstructured document text embeddings used in RAG semantic chat.

---

# PART 1: PostgreSQL Relational Database Schema

## Core Schema Rules

1. **Multi-Tenant Isolation**: Every tenant-specific table **MUST** include a `tenant_id` field. All application queries are strictly scoped using this identifier.
2. **Naming Conventions**: All tables and fields use `snake_case` (lowercase with underscores).
3. **Data Integrity**: Foreign keys are strictly enforced. Cascades are handled explicitly to protect historical financial information.

---

## 1. Table: `tenants`
*Stores details of tenant organizations subscribing to the SaaS platform.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the tenant. |
| `name` | `VARCHAR(255)` | `NOT NULL` | The company name or workspace title. |
| `domain` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | Company email domain (e.g. `acme.com`) used for automatic SSO provisioning. |
| `billing_plan` | `VARCHAR(50)` | `NOT NULL`, Default: `'free'` | Active pricing tier: `'free'`, `'pro'`, `'enterprise'`. |
| `free_invoices_remaining` | `INTEGER` | `NOT NULL`, Default: `50` | Ingestion quota limit remaining for the current billing cycle. |
| `stripe_customer_id` | `VARCHAR(255)` | `NULL` | Link to Stripe billing profile. |
| `stripe_subscription_id` | `VARCHAR(255)` | `NULL` | Link to Stripe active subscription status. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Timestamp when the tenant workspace was created. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Timestamp of the last workspace update. |

---

## 2. Table: `users`
*Stores user accounts and identities linked to individual tenants.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the user. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | The tenant workspace this user belongs to. |
| `email` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | User's email address. |
| `first_name` | `VARCHAR(100)` | `NULL` | User's first name. |
| `last_name` | `VARCHAR(100)` | `NULL` | User's last name. |
| `role` | `VARCHAR(50)` | `NOT NULL`, Check: `IN ('Admin', 'Auditor', 'Viewer')` | Access scope role inside the tenant workspace. |
| `clerk_user_id` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | External ID linked to Clerk/Auth0 Identity Provider. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Registration timestamp. |
| `last_login` | `TIMESTAMPTZ` | `NULL` | Last recorded login time. |

---

## 3. Table: `vendors`
*Stores authorized vendor registers for automatic match validation.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the vendor. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant owning this vendor contact list. |
| `name` | `VARCHAR(255)` | `NOT NULL` | Legal name of the vendor. |
| `tax_id` | `VARCHAR(100)` | `NULL` | Vendor Tax Registration/VAT/GST number. |
| `address` | `TEXT` | `NULL` | Vendor physical address. |
| `is_approved` | `BOOLEAN` | `NOT NULL`, Default: `TRUE` | Verification flag. Unapproved/unknown vendors trigger flags. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Date added to the system. |

---

## 4. Table: `purchase_orders`
*Stores purchase orders to match incoming invoice totals.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the PO. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant owning this PO. |
| `po_number` | `VARCHAR(100)` | `UNIQUE`, `NOT NULL` | Official purchase order reference code. |
| `vendor_id` | `UUID` | `FOREIGN KEY` references `vendors(id)`, `NOT NULL` | Target vendor. |
| `total_amount` | `DECIMAL(12, 2)` | `NOT NULL` | Pre-allocated total amount for this purchase. |
| `remaining_amount` | `DECIMAL(12, 2)` | `NOT NULL` | Balance remaining on this PO. |
| `status` | `VARCHAR(50)` | `NOT NULL`, Default: `'OPEN'` | Status: `'OPEN'`, `'FULLY_BILLED'`, `'CLOSED'`. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Date PO was generated. |

---

## 5. Table: `invoices`
*Stores structural meta-data extracted from ingested PDF invoices.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the invoice. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant owner. |
| `batch_id` | `UUID` | `NULL` | Group identifier for bulk uploads (tracked by SSE stream). |
| `file_path` | `VARCHAR(1024)` | `NOT NULL` | Azure Blob Storage URL to original PDF. |
| `invoice_number` | `VARCHAR(100)` | `NULL` | Invoice number extracted by AI. |
| `invoice_date` | `DATE` | `NULL` | Extracted invoice date. |
| `due_date` | `DATE` | `NULL` | Extracted due date. |
| `vendor_id` | `UUID` | `FOREIGN KEY` references `vendors(id)`, `NULL` | Matched vendor ID. |
| `subtotal` | `DECIMAL(12, 2)` | `NULL` | Calculated subtotal amount. |
| `tax_amount` | `DECIMAL(12, 2)` | `NULL` | Extracted tax amount. |
| `grand_total` | `DECIMAL(12, 2)` | `NULL` | Total amount payable. |
| `currency` | `VARCHAR(10)` | `NOT NULL`, Default: `'USD'` | Transaction currency code. |
| `po_number` | `VARCHAR(100)` | `NULL` | Extracted PO number (if present on invoice). |
| `tags` | `JSONB` | `NULL` | Array of classification tags added by the loader before uploading (e.g. `["#Q1-2026", "#Hardware"]`). |
| `alerts` | `JSONB` | `NULL` | List of active warning/anomaly alerts generated during extraction (e.g. `["Math mismatch"]`). Manually dismissed/removed by the auditor. |
| `status` | `VARCHAR(50)` | `NOT NULL`, Default: `'PROCESSING'` | Status state: `'PROCESSING'`, `'COMPLETED'`, `'AUDIT_REQUIRED'`, `'PAID'`, `'REJECTED'`. Invoices with active alerts remain in `'AUDIT_REQUIRED'` until resolved. |
| `audit_comments` | `TEXT` | `NULL` | Reasoning notes detailing flags, rejections, or alert resolutions. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Ingestion date. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Date of last field audit modification. |

---

## 6. Table: `invoice_items`
*Stores individual line items extracted from the invoice tables.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Line item identifier. |
| `invoice_id` | `UUID` | `FOREIGN KEY` references `invoices(id)` ON DELETE CASCADE, `NOT NULL` | Link to parent invoice metadata. |
| `description` | `TEXT` | `NOT NULL` | Description of item/service provided. |
| `quantity` | `DECIMAL(10, 4)` | `NULL` | Number of units purchased. |
| `unit_price` | `DECIMAL(12, 4)` | `NULL` | Cost per unit. |
| `amount` | `DECIMAL(12, 2)` | `NOT NULL` | Calculated total amount for this row. |

---

## 7. Table: `audit_logs`
*Stores change history and system verification actions for audits.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Log identifier. |
| `invoice_id` | `UUID` | `FOREIGN KEY` references `invoices(id)`, `NOT NULL` | Target invoice. |
| `actor_id` | `UUID` | `FOREIGN KEY` references `users(id)`, `NULL` | User who made the change. (System actions show `NULL`). |
| `action` | `VARCHAR(100)` | `NOT NULL` | Action: `'FLAGGED_MATH_ERROR'`, `'MARKED_AS_PAID'`, `'UPDATED_LINE_ITEMS'`, `'REJECTED'`. |
| `previous_state` | `JSONB` | `NULL` | Snapshot of fields before update. |
| `new_state` | `JSONB` | `NULL` | Snapshot of fields after update. |
| `timestamp` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Event timestamp. |

---

## 8. Table: `extraction_templates`
*Stores structural mapping coordinates generated by the Trainer Agent.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Template identifier. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant owner. |
| `vendor_id` | `UUID` | `FOREIGN KEY` references `vendors(id)`, `NOT NULL` | Vendor this template matches. |
| `rules` | `JSONB` | `NOT NULL` | Coordinate keys, anchors, and parsing offsets generated by the Trainer Agent. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Template generation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Last modification date. |

---

## 9. Table: `chat_sessions`
*Stores semantic conversation threads.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Chat session identifier. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant workspace. |
| `user_id` | `UUID` | `FOREIGN KEY` references `users(id)`, `NOT NULL` | Chat creator. |
| `title` | `VARCHAR(255)` | `NOT NULL`, Default: `'New Chat'` | Conversation summary name. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Chat started date. |

---

## 10. Table: `chat_messages`
*Stores conversational RAG message exchanges.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Message identifier. |
| `session_id` | `UUID` | `FOREIGN KEY` references `chat_sessions(id)` ON DELETE CASCADE, `NOT NULL` | Active chat session thread. |
| `sender_type` | `VARCHAR(50)` | `NOT NULL`, Check: `IN ('user', 'assistant')` | Identifies message sender. |
| `content` | `TEXT` | `NOT NULL` | The message text (Markdown supported). |
| `citations` | `JSONB` | `NULL` | List of reference invoice IDs and source PDF links. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Message timestamp. |

---

# PART 2: ChromaDB Vector Store Collections

ChromaDB is a document-based vector database and does not use a rigid, structured SQL schema. Instead, it is organized into **Collections** containing four key data layers per record.

## Collection: `invoice_chunks`
*Stores the vectorized text chunks of ingested invoices to power semantic query matches.*

| Field Name | Data Type | Constraints / Format | Description |
| :--- | :--- | :--- | :--- |
| **`id`** | `String (UUID)` | Generated locally upon insertion | Matches the text chunk ID (or derived from the SQL `invoice_id`). |
| **`embeddings`** | `List[Float]` | Must be exactly **1024 dimensions** | Vector representation of the text chunk calculated locally using `BAAI/bge-m3`. |
| **`document`** | `String` | Raw UTF-8 Text String | The actual extracted text segment containing invoice names, line item tables, and numerical balances. |
| **`metadata`** | `JSON Object` | Enforced at the application level | Structural query tags. See metadata schema definition below. |

### Enforced Metadata Schema (Application-Layer)

Every record inserted into the `invoice_chunks` collection must possess the following metadata keys for RAG accuracy and security:

```json
{
  "tenant_id": "uuid-value",       // Mandatory. Used to filter query scope per organization.
  "invoice_id": "uuid-value",      // Links vector results back to PostgreSQL invoices table.
  "vendor_name": "Vendor Co.",     // Used to restrict search context to specific suppliers.
  "page_number": 1                 // For PDF viewer page citation alignments.
}
```

---

# PART 3: Database Migrations & Version Control (Alembic)

To support schema updates in production without causing downtime or data loss, database version control is managed using **Alembic**.

## 1. Migration Strategy
* **Auto-Generation**: Migrations are auto-generated by comparing current models inside `models.py` (SQLModel classes) against the live database state.
* **Production Deployment**: The CI/CD pipeline triggers migration scripts during the release step before running containers.
* **Git Versioning**: Migration files (`/apps/invoice-be/migrations/versions/*.py`) are committed to Git to track exactly how and when the schema evolved.

## 2. Standard Commands

* **Create a new migration script**:
  ```bash
  # Generate a migration script after modifying models.py
  uv run alembic revision --autogenerate -m "add_columns_to_tenants"
  ```
* **Apply migrations to database (Dev/UAT/Prod)**:
  ```bash
  # Upgrades the database schema to the latest version
  uv run alembic upgrade head
  ```
* **Roll back a migration**:
  ```bash
  # Reverts the database to the previous migration step
  uv run alembic downgrade -1
  ```


