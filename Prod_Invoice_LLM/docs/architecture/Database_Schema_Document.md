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
| `billing_plan` | `VARCHAR(50)` | `NOT NULL`, Default: `'free'` | Active pricing tier: `'free'`, `'pro'`, `'pro_combined'`, `'unpaid'`. |
| `free_invoices_remaining` | `INTEGER` | `NOT NULL`, Default: `50` | Ingestion quota limit remaining for the current billing cycle. |
| `payu_customer_id` | `VARCHAR(255)` | `NULL` | Reference identifier for the tenant on PayU's side (email used as the customer key — PayU's classic API has no stored customer object). |
| `payu_subscription_id` | `VARCHAR(255)` | `NULL` | The most recent successful `txnid`/`mihpayid` that renewed this tenant's plan. Not a native subscription object — PayU's classic hash-based API is one-time-payment; "subscription" here just tracks the last renewal transaction that set the current `billing_plan`, since billing is a manual monthly re-payment flow, not auto-debit. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Timestamp when the tenant workspace was created. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Timestamp of the last workspace update. |
| `receive_invoices_enabled` | `BOOLEAN` | `NOT NULL`, Default: `TRUE` | Service Flow — inbound AP processing enabled. |
| `send_invoices_enabled` | `BOOLEAN` | `NOT NULL`, Default: `FALSE` | Service Flow — outbound AR processing enabled. |
| `outbound_sender_email` | `VARCHAR(255)` | `NULL` | Legacy; customer-delivery Reply-To placeholder (Gap 125). Email Setup uses `tenant_email_senders` instead. |

---

## 1b. Table: `tenant_email_senders`

*Authorized tenant-owned emails that may send invoice PDFs to the **global** app mailbox `invoices@invoiceeq.app`. Tenant + direction come from this row (`email_set`), not from the recipient address. `email` is unique platform-wide.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY` | Row id. |
| `tenant_id` | `UUID` | `FK → tenant.id`, indexed | Owning tenant. |
| `email` | `VARCHAR(255)` | indexed, lowercased, **UNIQUE** | Authorized sender address (one workspace only). |
| `email_set` | `VARCHAR(20)` | `NOT NULL`, Default `'inbound'`, Check: `IN ('inbound','outbound')` | AP inbound vs AR outbound audit. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | When registered. |

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
| `submitted_by_email` | `VARCHAR(255)` | `NULL` | Gap 125: who submitted the PDF (email ingest From, or UI uploader). Used for process-complete staff notify; never used to email end customers. |
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

## 9. Table: `tenant_autopilot_configs`
*Stores Autopilot folder synchronization and automation settings per tenant workspace.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Autopilot config identifier. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL`, indexed | Tenant owner (single active configuration per tenant). |
| `source_type` | `VARCHAR(50)` | `NOT NULL` | The source integration type: `'gdrive'`, `'salesforce'`, `'email'`. |
| `source_ref` | `VARCHAR(1024)` | `NOT NULL` | The folder reference or library path (e.g. Google Drive Folder ID or Salesforce Directory ID). |
| `flow_direction` | `VARCHAR(10)` | `NOT NULL`, Default: `'INBOUND'` | Flow direction: `'INBOUND'` (AP flow, extraction queued) or `'OUTBOUND'` (AR flow, record-keeping). |
| `trigger_mode` | `VARCHAR(20)` | `NOT NULL` | Scheduling trigger mode: `'interval'` (minutes) or `'cron'` (cron expression). |
| `trigger_value` | `VARCHAR(100)` | `NOT NULL` | The schedule value (e.g., `'60'` for hourly interval, or `'0 * * * *'` for cron). |
| `notify_emails` | `JSONB` | `NOT NULL`, Default: `'[]'` | Array of email strings to notify upon completed/failed runs. |
| `send_approval_links` | `BOOLEAN` | `NOT NULL`, Default: `FALSE` | Toggle to include one-click manual audit links in the notification emails. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Config creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Config last updated. |

---

## 10. Table: `tenant_autopilot_logs`
*Deduplication ledger tracking files processed by scheduled and manual Autopilot sync operations.*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `gen_random_uuid()` | Autopilot run log entry identifier. |
| `tenant_id` | `UUID` | `FOREIGN KEY` references `tenants(id)`, `NOT NULL`, indexed | Tenant owner. |
| `source_type` | `VARCHAR(50)` | `NOT NULL` | Ingestion source: `'gdrive'`, `'salesforce'`, `'email'`, `'manual'`. |
| `source_file_id` | `VARCHAR(255)` | `NOT NULL`, indexed | Cloud source identifier (e.g., Google Drive `fileId` or Salesforce record ID). |
| `content_hash` | `VARCHAR(64)` | `NOT NULL`, indexed | SHA-256 hash of the document content to catch duplicates uploaded under different file IDs. |
| `ingested_at` | `TIMESTAMPTZ` | `NOT NULL`, Default: `NOW()` | Ingestion timestamp. |
| `status` | `VARCHAR(50)` | `NOT NULL` | Status outcome of the ingestion run: `'SUCCESS'`, `'SKIPPED_DUPLICATE'`, or `'FAILED'`. |

---

## 11. Table: `supportticket`
*Single ledger for every inbound support interaction — public website contact inquiries, AI-escalated Help Center tickets, and manually raised tickets (BE Feature 19 / Website Feature 5 / FE Feature 15; Gaps 183, 246–248). Added by Alembic revision `6c60f6e907a0`. Two deviations from the conventions above, both as-generated by SQLModel and deliberately left alone rather than silently "corrected" in this doc: the table name is one unbroken word (`supportticket`) rather than snake_case, and its timestamps are naive `TIMESTAMP` rather than `TIMESTAMPTZ` (`datetime.utcnow()` in the model, `sa.DateTime()` in the migration).*

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | `PRIMARY KEY`, Default: `uuid4()` | Ticket identifier. |
| `ticket_number` | `VARCHAR(32)` | `UNIQUE`, indexed, `NOT NULL` | Human-visible reference. `INQ-YYYY-XXXXXXXX` for website inquiries, `TICK-YYYY-XXXXXXXX` for in-app tickets. Suffix is 8 uppercase hex chars from `secrets.token_hex(4)` — Gap 251 replaced a 4-digit random suffix whose 9,000 values/year/prefix were exhaustible by unauthenticated POSTs. |
| `tenant_id` | `UUID` | indexed, `NULL` | Owning tenant. **Nullable by design** — website contact submissions are anonymous and belong to no workspace. No FK constraint. |
| `user_id` | `UUID` | `NULL` | Submitting user, when authenticated. Null for website inquiries. |
| `user_email` | `VARCHAR(255)` | indexed, `NOT NULL` | Submitter's email — form-supplied for website inquiries, resolved from the `users` row for in-app tickets. |
| `user_name` | `VARCHAR(255)` | `NULL` | Submitter's name (form-supplied, or `first_name + last_name`). |
| `source` | `VARCHAR(32)` | `NOT NULL`, Default: `'WEBSITE_CONTACT'` | `'WEBSITE_CONTACT'` (public `/contact` form), `'HELP_CHATBOT'` (escalated from the Help Center assistant), `'DIRECT_TICKET'` (manually raised in the Help Center). Validated in the router, not by a DB check constraint. |
| `category` | `VARCHAR(64)` | `NOT NULL`, Default: `'GENERAL'` | `'SALES'`, `'TECHNICAL_SUPPORT'`, `'BILLING'`, `'PARTNERSHIP'`, `'GENERAL'`. Unrecognized values coerce to `'GENERAL'`. |
| `priority` | `VARCHAR(32)` | `NOT NULL`, Default: `'NORMAL'` | `'LOW'`, `'NORMAL'`, `'URGENT'` — drives the SLA line in the acknowledgement email. |
| `subject` | `VARCHAR(255)` | `NOT NULL` | Ticket subject. Website inquiries synthesize `[CATEGORY] Contact inquiry from {name}`, truncated to 255 before persistence; in-app subjects are stripped of CR/LF (header-injection defence, Gap 250). |
| `description` | `TEXT` | `NOT NULL` | Free-text message body (capped at 5,000 chars on the public form). |
| `company_name` | `VARCHAR(255)` | `NULL` | Optional company supplied by the submitter. |
| `chat_transcript` | `JSONB` | `NULL`, Default: `[]` | Full assistant conversation attached when a ticket is escalated from the Help Center chatbot. `JSON` with a `JSONB` variant on PostgreSQL. |
| `status` | `VARCHAR(32)` | `NOT NULL`, Default: `'OPEN'` | Lifecycle: `'OPEN'`, `'IN_PROGRESS'`, `'RESOLVED'`, `'CLOSED'`. No endpoint mutates this yet — triage happens over email today. |
| `admin_notes` | `TEXT` | `NULL` | Internal triage notes. Not yet written by any endpoint. |
| `created_at` | `TIMESTAMP` | `NOT NULL`, Default: `utcnow()` | Submission timestamp. |
| `updated_at` | `TIMESTAMP` | `NOT NULL`, Default: `utcnow()` | Last modification. |

**Indexes**: `ix_supportticket_ticket_number` (unique), `ix_supportticket_tenant_id`, `ix_supportticket_user_email`.

> **Tenant-rule note.** The table carries `tenant_id` as *Core Schema Rules* requires, but — uniquely among the tables above — it is nullable and unenforced by a foreign key: `POST /api/v1/support/contact` is public and unauthenticated, so an inquiry from an anonymous website visitor has no tenant to attribute. Reads are still strictly tenant-scoped — `GET /api/v1/support/tickets` filters on `tenant_id == context.tenant_id`, so anonymous rows (`tenant_id IS NULL`) are never returned to any workspace.

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
* **Git Versioning**: Migration files (`/apps/invoice-be/alembic/versions/*.py`) are committed to Git to track exactly how and when the schema evolved.

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

---

# PART 4: Service Flow (Outbound) — Planned Additive Schema

**Status: fully unimplemented — spec-only.** Listed here for review before any migration is written; every column below is additive (nullable or defaulted) so no existing row or query is affected. Full detail: `apps/invoice-be/docs/feature_2.1_vendor_flow_ingestion.md`, `feature_7.1_vendor_flow_auditor.md`, `feature_8.1_vendor_flow_dashboard.md`, `feature_16_settings.md`.

### New columns on `invoices`
| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `flow_direction` | `VARCHAR(10)` | `NOT NULL`, Default: `'INBOUND'` | `'INBOUND'` (today's vendor→tenant flow, unaffected) or `'OUTBOUND'` (tenant→customer). |
| `customer_name` | `VARCHAR(255)` | `NULL` | Extracted "bill to" name on outbound invoices only. |
| `customer_id` | `UUID` | `NULL` | Reserved for future customer-record linking; unused in v1 (no customer portal exists). |
| `sent_at` | `TIMESTAMPTZ` | `NULL` | Set when an outbound invoice transitions `VERIFIED → SENT`. Drives real `average_days_to_payment`. |
| `paid_at` | `TIMESTAMPTZ` | `NULL` | Set when an outbound invoice transitions `SENT → PAID`. |

### New columns on `extraction_templates`
| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `flow_direction` | `VARCHAR(10)` | `NOT NULL`, Default: `'INBOUND'` | An `'OUTBOUND'` row (always `vendor_name IS NULL`, Global-only) is a standing correction rule for the tenant's own outbound document format — no per-vendor equivalent, since outbound has no vendor-style format variability. |

### New columns on `tenants`
| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `receive_invoices_enabled` | `BOOLEAN` | `NOT NULL`, Default: `true` | Admin-only toggle; `true` for every existing tenant, preserving current behavior exactly. |
| `send_invoices_enabled` | `BOOLEAN` | `NOT NULL`, Default: `false` | Admin-only toggle; opt-in, gates every outbound screen/endpoint. |

### Outbound invoice status values (new, not added to the existing `invoices.status` CHECK constraint's documented set above — tracked here pending implementation)
`UPLOADED`, `PROCESSING_OCR`, `EXTRACTING_DATA`, `VERIFIED`, `NEEDS_REVIEW`, `SENT`, `PAID`, `OVERDUE` (the last computed at read-time in v1, not persisted — see `feature_7.1`).


