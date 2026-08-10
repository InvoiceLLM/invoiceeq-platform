# Feature 14: Email-Based Invoice Ingestion & Outbound Delivery

1. **Email ingestion (both directions):** PDFs emailed to the **one global** app mailbox. Tenant + direction come from the sender’s registered set. Dual-set redesign **2026-08-10**; global mailbox (not per-tenant) confirmed same day.
2. **Customer outbound delivery:** Gap 125 — not built.

### Product model
* **Mailbox:** `EMAIL_APP_ADDRESS` (default `invoices@invoiceeq.app`) — shared by all tenants.
* **Registry:** `tenant_email_senders(tenant_id, email, email_set)` with **globally unique `email`**.
* **Webhook (one shared URL):** `POST /api/v1/email/mailintegration` — SendGrid always hits this; app branches inbound vs outbound from `From`.

### File Coordinates
* `routers/email_ingestion.py` — `email_mailintegration_webhook` + set CRUD + mailbox
* `models.py::TenantEmailSender` — migrations `71d18e2c3349` + `e8f9a0b1c2d3`
* Config: `EMAIL_APP_ADDRESS`, `EMAIL_APP_DOMAIN`
* Tests: `tests/test_email_ingestion.py`

### Tasks
- [x] **14.1–14.4:** SendGrid choice, ingest helper, allow-list, webhook (2026-07-28).
- [x] **14.5:** FE Email Setup — FE Feature 8.
- [x] **14.7:** Dual sets + direction-by-sender; global mailbox; unique sender email.
- [ ] **14.6:** Customer send — Gap 125.

### Verification
Pytest covers mailbox, CRUD by set, drop unknown sender, inbound/outbound PDF paths. Live SendGrid still Gap 124 — Inbound Parse Destination URL should be `…/api/v1/email/mailintegration`.
