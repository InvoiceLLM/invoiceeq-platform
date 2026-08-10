# Feature 14: Email mailintegration & staff notifications

1. **Email ingestion (both directions):** PDFs emailed to the **one global** app mailbox. Tenant + direction from the sender’s registered set.
2. **Staff email notifications (Gap 125):** SendGrid Mail Send to **registered** addresses only. **Never** email customers from this app — staff forward to customers themselves.

### Product model (decided 2026-08-10)
* **Mailbox:** `EMAIL_APP_ADDRESS` (shared). Webhook: `POST /api/v1/email/mailintegration`.
* **Public URL:** BE ingress is internal-only. Same PayU topology — `invoice-website` relays `POST /api/v1/email/mailintegration` → internal BE (`apps/invoice-website/app/api/v1/email/mailintegration/route.ts`). SendGrid Inbound Parse Destination = **website** FQDN + that path.
* **Registry:** `tenant_email_senders` — globally unique `email` + `email_set` inbound|outbound.
* **`Invoice.submitted_by_email`:** set on email ingest (and UI upload when known) so later notifies know the submitter.
* **Notify #1 — after processing finishes:** one email to submitter (fallback: direction’s registered set) — *Completed* or *Audit pending*, optionally listing alerts.
* **Notify #2 — auditor actions:** Mark Paid / Reject (inbound) or Confirm Send / Mark Paid (outbound). Auditor **multi-selects** registered emails of that direction before clicking; BE sends only to the selected list (must be subset of the set).
* **Not in scope:** attaching/sending the invoice PDF to an end customer; developer HTTP webhooks (Feature 15) remain a separate JSON channel.

### SendGrid
* **Receive:** Inbound Parse → website relay → BE `mailintegration`. **Gap 124** = GoDaddy MX/DNS + Parse host settings + authenticity/size/failed-mail hardening + live E2E (public proxy itself is done).
* **Send:** `SENDGRID_API_KEY` Mail Send API. Single Sender Verification is enough to *call* the API without GoDaddy domain auth; domain auth improves inbox placement (also tracked under Gap 124 / Gap 125 live verify).

### File Coordinates
* `routers/email_ingestion.py` — mailintegration + set CRUD + mailbox
* `invoice-website/.../api/v1/email/mailintegration/route.ts` — public relay
* `services/outbound_email.py` — SendGrid send helper
* `models.py::TenantEmailSender`, `Invoice.submitted_by_email`
* Config: `EMAIL_APP_ADDRESS`, `EMAIL_APP_DOMAIN`, `SENDGRID_API_KEY`, `SENDGRID_SENDING_DOMAIN`

### Tasks
- [x] **14.1–14.5 / 14.7:** Provider choice, ingest, dual sets, global mailbox, FE Email Setup.
- [x] **14.6 / Gap 125 (code):** Staff notify via SendGrid — `submitted_by_email`, process-complete + auditor `notify_emails[]`, FE multi-select.
- [x] **14.8 / Gap 124 (public URL):** Website mailintegration relay (2026-08-10).
- [ ] **Gap 124 leftovers:** GoDaddy MX + SendGrid Inbound Parse Destination + authenticity + size cap + E2E.

### Verification
Unit tests for send helper + confirm-send/resolve with `notify_emails`. Website e2e: `email-mailintegration-relay.spec.ts` (unreachable-backend 502). Live receive still needs Gap 124 DNS/Parse.
