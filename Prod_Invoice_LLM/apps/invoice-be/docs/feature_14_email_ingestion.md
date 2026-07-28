# Feature 14: Email-Based Invoice Ingestion & Outbound Delivery

Symmetric email capability:
1. **Inbound Email Ingestion**: Accept invoices sent directly to a per-tenant inbound email alias (forward/CC invoices to a fixed address).
2. **Outbound Email Delivery**: Send verified outbound invoices automatically to customer emails via the tenant's configured outbound sender email.

### Decision point — flagged for sign-off before Task 1 starts
**Azure Communication Services Email vs. SendGrid Inbound Parse** for
receiving inbound mail:
- **ACS Email**: same cloud (Azure), same billing/IAM surface as the rest
  of the stack, Event Grid delivers inbound events — but ACS Email's
  *inbound* parsing/routing is less mature than SendGrid's purpose-built
  Inbound Parse webhook.
- **SendGrid Inbound Parse**: mature, POSTs a fully-parsed MIME payload
  (headers, body, attachments) directly to a webhook URL — less plumbing
  on our side — but it's a second vendor/billing relationship outside Azure.
- Both fit the same downstream design (webhook → tenant resolution →
  attachment extraction → existing ingestion path); this doc doesn't
  implement Task 1 until one is picked.

### File Coordinates
* Upload endpoint (reused, not duplicated): [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py) → `upload_invoices()`
* New inbound webhook: `apps/invoice-be/routers/email_ingestion.py` *(not yet created)* → `POST /api/v1/email/inbound`
* Tenant model: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py) → `Tenant` (alias derives from existing `Tenant.id`, no new field needed); new `TenantEmailSender` table for the allowed-senders list

### Functionality (target design)
Each tenant gets a fixed inbound alias `{tenant_id}@invoices.{platform-domain}`
— derived from the existing `Tenant.id` UUID, so no new alias-storage field
is needed and the alias can't be guessed/enumerated. The email provider
(ACS/SendGrid, per the decision above) POSTs inbound mail to
`POST /api/v1/email/inbound` as a webhook (provider-signature verified,
**not** tenant-authenticated — this endpoint has no logged-in user). The
handler: (1) resolves `tenant_id` from the alias in the `To` header, 404s
if unknown; (2) checks the `From` address against that tenant's
`TenantEmailSender` allow-list, silently drops (200 OK, no processing) if
not allowed — a fixed response either way avoids leaking which senders
are allowed; (3) extracts PDF attachments only (rejects/ignores others);
(4) calls the same core ingestion logic `upload_invoices()` already uses,
refactored into a shared `_ingest_invoice_files(tenant_id, files, tags,
db_session)` helper so both the authenticated multipart endpoint and this
webhook share one code path instead of duplicating it (the exact
duplication pattern Gap 35 just got removed for).

### Tasks
- [ ] **Task 14.1: Vendor decision + provider account setup** — per the
      decision point above; provision the inbound-mail resource and DNS
      (MX/webhook registration) for `invoices.{platform-domain}`.
- [ ] **Task 14.2: Refactor `upload_invoices()`** — extract
      `_ingest_invoice_files()` as a shared helper, called by both the
      existing multipart endpoint and the new webhook, so upload
      validation/blob storage/DB row creation/queue dispatch has one
      implementation.
- [ ] **Task 14.3: `TenantEmailSender` allow-list model + management endpoints**
      — `GET/POST/DELETE /api/v1/settings/email-senders`, tenant-scoped.
- [ ] **Task 14.4: Inbound webhook endpoint** — `POST /api/v1/email/inbound`,
      provider-signature verification, tenant resolution via alias,
      sender allow-list check, PDF attachment extraction, dispatch via
      Task 14.2's shared helper.
- [ ] **Task 14.5: Surface the alias in Settings UI** — see
      `feature_8_email_ingestion.md` (FE).

### Verification Plan
* **Automated Tests**: webhook signature rejection, unknown-alias 404,
  disallowed-sender silent-drop, PDF-attachment happy path landing in the
  same `Invoice` row shape as a manual upload.
* **Manual Verification**: send a real email with a PDF attachment to a
  test tenant's alias, confirm it appears in the ingestion queue exactly
  like a UI upload.
