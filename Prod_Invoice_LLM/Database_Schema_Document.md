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

*Stores user accounts and identities linked to individual tenants. Populated on first SSO login via domain-based tenant/role provisioning; `AuditLog.actor_user_id` is a foreign key into this table.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the user. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NULL` | The tenant workspace this user belongs to. Nullable during initial signup/onboarding phase before a tenant is created/joined (placeholder for future invite flows). |
| `email` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | User's email address. |
| `first_name` | `VARCHAR(100)` | `NULL` | User's first name. |
| `last_name` | `VARCHAR(100)` | `NULL` | User's last name. |
| `role` | `VARCHAR(50)` | `NOT NULL`, Check: `IN ('Admin', 'Auditor', 'Viewer')` | Access scope role inside the tenant workspace. |
| `clerk_user_id` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | External ID linked to Clerk/Auth0 Identity Provider. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Registration timestamp. |
| `last_login` | `TIMESTAMPTZ` | `NULL` | Last recorded login time. |

---

## 3. Table: `invoices`
*Stores structural meta-data extracted from ingested PDF invoices. Reflects the actual `Invoice` SQLModel in `apps/invoice-be/models.py`.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Unique identifier for the invoice. |
| `tenant_id` | `UUID` | `INDEX`, `NOT NULL` | Tenant owner. |
| `batch_id` | `UUID` | `INDEX`, `NULL` | Group identifier for bulk uploads (tracked by SSE stream). |
| `file_path` | `VARCHAR(1024)` | `NOT NULL` | Blob URL, or local filesystem fallback path. |
| `file_hash` | `VARCHAR(64)` | `INDEX`, `NULL` | SHA-256 hash of the uploaded file bytes, used for Layer 1 duplicate detection. |
| `invoice_number` | `VARCHAR(100)` | `NULL` | Invoice number extracted by AI. |
| `vendor_name` | `VARCHAR(255)` | `NULL` | Extracted vendor name. |
| `invoice_date` | `DATE` | `NULL` | Extracted invoice date. |
| `due_date` | `DATE` | `NULL` | Extracted due date. |
| `tax_amount` | `DECIMAL(12, 2)` | `NULL` | Extracted tax amount. |
| `grand_total` | `DECIMAL(12, 2)` | `NULL` | Total amount payable. |
| `po_number` | `VARCHAR(100)` | `NULL` | Extracted PO number (if present on invoice). |
| `tags` | `JSONB` | `NULL` | Array of classification tags added by the loader before uploading (e.g. `["#Q1-2026", "#Hardware"]`). |
| `items` | `JSONB` | `NULL` | List of individual extracted line items (description, quantity, unit_price, amount) stored as a native JSON array. |
| `coordinates` | `JSONB` | `NULL` | Per-field bounding boxes (`{x, y, width, height, label}[]`) sourced from the `prebuilt-invoice` OCR model, powering the auditor UI's PDF coordinate overlay. |
| `field_confidence` | `JSONB` | `NULL` | Per-field confidence scores, driving the Critic Node's field-level (rather than document-level) audit routing. |
| `sa_alerts` | `JSONB` | `NULL` | List of active warning/anomaly alert objects (e.g. `{"type": "tax_mismatch", "message": "...", "field": "tax_amount"}`). Manually dismissed/removed by the auditor. |
| `status` | `VARCHAR(50)` | `NOT NULL`, Default: `'PROCESSING'`, `CHECK` | `'PROCESSING'`, `'COMPLETED'`, `'AUDIT_REQUIRED'`, `'PAID'`, `'REJECTED'`, or `'DUPLICATE'`. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Ingestion date. |

---

## 4. Table: `audit_logs`
*Stores change history and system verification actions for audits.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Log identifier. |
| `tenant_id` | `UUID` | `INDEX`, `NOT NULL` | Tenant owner. |
| `invoice_id` | `UUID` | `INDEX`, `NOT NULL` | Target invoice. |
| `actor_user_id` | `UUID` | `FOREIGN KEY` references `users(id)`, `NOT NULL` | The user who performed the action. |
| `actor_role` | `VARCHAR(50)` | `NOT NULL` | Role held by the actor at the time of the action. |
| `action` | `VARCHAR(255)` | `NOT NULL` | e.g. `'RESOLVE_INVOICE'`. |
| `details` | `JSONB` | `NULL` | Context object for the action (e.g. `target_status`, `dismissed_alerts_input`, `previous_alerts`, `remaining_alerts`). |
| `timestamp` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Event timestamp. |

---

## 5. Table: `extraction_templates`
*Stores per-vendor extraction rules generated by the Trainer Agent.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Template identifier. |
| `tenant_id` | `UUID` | `INDEX`, `NOT NULL` | Tenant owner. |
| `vendor_name` | `VARCHAR(255)` | `NOT NULL` | Vendor name this template matches. |
| `rules` | `JSONB` | `NOT NULL` | `{"constraints": ["plain-English rule", ...], "coordinate_anchors": {...}}` — natural-language extraction constraints plus coordinate anchors synthesized by the Trainer Agent from auditor corrections. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Template generation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Last modification date. |

---

## 6. Tables: `chat_sessions` + `chat_messages`
*Conversation threads and message history are two separate tables — messages need independent pagination and per-message metadata rather than always loading the full thread.*

**`chat_sessions`**

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Chat session identifier. |
| `tenant_id` | `UUID` | `INDEX`, `NOT NULL` | Tenant workspace. |
| `user_id` | `UUID` | `FOREIGN KEY` references `users(id)`, `NOT NULL` | Owning user. |
| `title` | `VARCHAR(255)` | `NOT NULL` | Conversation summary name. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Chat started date. |

**`chat_messages`**

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Message identifier. |
| `session_id` | `UUID` | `INDEX`, `NOT NULL` | Parent chat session. |
| `role` | `VARCHAR(50)` | `NOT NULL` | `'user'` or `'assistant'`. |
| `content` | `TEXT` | `NOT NULL` | Message text. |
| `generated_sql` | `TEXT` | `NULL` | The SQL statement generated for this turn, if the query routed to the SQL path. |
| `citations` | `JSONB` | `NULL` | List of `{invoice_id, vendor_name, page}` citation objects, if the query routed to the RAG path. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Message timestamp. |

---

## 7. Table: `chat_qa_shortcuts`
*Custom Q&A registry and semantic result cache for the Query Agent — instant answers for frequently repeated questions.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Shortcut identifier. |
| `tenant_id` | `UUID` | `INDEX`, `NOT NULL` | Tenant owner. |
| `normalized_query` | `VARCHAR(500)` | `INDEX`, `NOT NULL` | Normalized form of the cached/registered question. |
| `answer` | `TEXT` | `NOT NULL` | The instant answer served without re-running retrieval + LLM synthesis. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Registration timestamp. |

---

## 8. Table: `tenant_connections`
*Stores third-party API OAuth credentials and tokens securely per tenant.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Connection identifier. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL` | Tenant owner. |
| `provider` | `VARCHAR(50)` | `NOT NULL` | The integration provider (e.g. `'google_drive'`, `'salesforce'`). |
| `encrypted_access_token` | `TEXT` | `NOT NULL` | Access token encrypted at rest via AES-256 Fernet. |
| `encrypted_refresh_token` | `TEXT` | `NULL` | Refresh token encrypted at rest via AES-256 Fernet. |
| `token_expiry` | `TIMESTAMPTZ` | `NOT NULL` | Access token expiration timestamp. |
| `status` | `VARCHAR(50)` | `NOT NULL`, Default: `'active'` | Status: `'active'`, `'revoked'`, `'error'`. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Connection timestamp. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Connection last updated. |

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


