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
* **Receive:** Inbound Parse → website relay → BE `mailintegration`. **Gap 124** = GoDaddy MX/DNS + Parse host settings + live E2E (public proxy done 2026-08-10; authenticity/size/dropped-mail hardening done 2026-08-12 — see *Webhook hardening* below).
* **Send:** `SENDGRID_API_KEY` Mail Send API. Single Sender Verification is enough to *call* the API without GoDaddy domain auth; domain auth improves inbox placement (also tracked under Gap 124 / Gap 125 live verify).

### Webhook hardening (Gap 124 items 5–7, 2026-08-12)

The mailintegration webhook is the only endpoint in the app with no
authenticated caller — SendGrid holds no Clerk session — so it carries its own
three guards, all in front of the ingestion logic.

**Authenticity.** `INBOUND_PARSE_SHARED_SECRET` (already wired in
`infra/modules/compute/invoice-be.bicep` from Key Vault `SENDGRID-INBOUND-SECRET`,
but read by nothing until now) is compared with `hmac.compare_digest`. SendGrid
Inbound Parse offers no request signing at all — a Destination URL is the only
configurable thing — so the secret has to ride in that URL, and
`presented_inbound_secret` accepts an `X-Inbound-Secret` /
`X-Sendgrid-Inbound-Secret` header, a `?key=` / `?secret=` query parameter, or
the password half of Basic credentials in the URL. **Fail-closed:** an empty
setting rejects everything (reason `secret_unconfigured`) rather than meaning
"enforcement off", the same choice as `ALLOW_MOCK_AUTH`.

**25 MiB cap** (`INBOUND_EMAIL_MAX_BYTES`), checked twice: against the declared
`Content-Length` *before* the body is touched (the check that matters — Starlette
spools multipart to a temp file while parsing), then against the measured
attachment bytes for a chunked client that declares no length.

**Dropped-mail visibility.** Every rejection path writes a `DroppedInboundEmail`
row (`unverified_secret`, `secret_unconfigured`, `oversized`, `malformed`,
`unknown_sender`, `missing_tenant`, `no_pdf_attachment`, `quota_exhausted`,
`ingest_rejected`, `ingest_failed`) and the Admin console renders them. Each of
those paths was previously a `logger.warning` plus a 200 — mail vanished with no
trace visible outside the container.

Two structural deviations from the original plan, both forced by what the code
actually does:

1. **The handler parses its own body.** FastAPI reads and parses the request
   body *before* it solves dependencies, so a declared
   `Form(...)`/`File(...)` signature (or a `Depends` guard) offers no point at
   which the size cap or the secret can run first. The handler now takes
   `Request` and calls `await request.form()` itself.
2. **Attachments are collected by type, not field name.** The old signature was
   `files: list[UploadFile]`, which only ever matched a part literally named
   `files` — and real SendGrid Inbound Parse names them `attachment1`,
   `attachment2`, … So the one field name the handler accepted was the one name
   SendGrid never sends; this could not have worked against live Parse traffic
   as written. `_collect_attachments` now takes every file part regardless of
   name (both shapes covered by tests).

The website relay had to change too: it forwarded only `Content-Type`, dropping
the query string and every header, so enforcing the secret backend-side without
that fix would have rejected 100% of real inbound mail.

### File Coordinates
* `routers/email_ingestion.py` — mailintegration webhook (`email_mailintegration_webhook`, `_collect_attachments`, `_attachment_size`) + set CRUD + mailbox
* `services/inbound_mail_security.py` — `verify_inbound_secret`, `presented_inbound_secret`, `oversize_from_content_length`, `declared_content_length`, `max_inbound_bytes`, `sender_domain_of`, `describe_client`, `record_dropped_email`, `DROP_REASONS`
* `routers/admin.py` — `list_dropped_emails` (`GET /api/v1/admin/dropped-emails`), `_tenant_email_domains`, `DroppedEmailOut`
* `invoice-website/.../api/v1/email/mailintegration/route.ts` — public relay (forwards secret + query string, 413s oversized)
* `invoice-fe/app/api/admin/dropped-emails/route.ts` + `invoice-fe/app/admin/page.tsx` (`loadDroppedEmails`, `DROP_REASON_LABELS`) — Admin console panel
* `services/outbound_email.py` — SendGrid send helper
* `models.py::TenantEmailSender`, `models.py::DroppedInboundEmail`, `Invoice.submitted_by_email`
* Migration: `alembic/versions/a2b3c4d5e6f7_add_dropped_inbound_emails.py`
* Config: `EMAIL_APP_ADDRESS`, `EMAIL_APP_DOMAIN`, `SENDGRID_API_KEY`, `SENDGRID_SENDING_DOMAIN`, `INBOUND_PARSE_SHARED_SECRET`, `INBOUND_EMAIL_MAX_BYTES`

### Tasks
- [x] **14.1–14.5 / 14.7:** Provider choice, ingest, dual sets, global mailbox, FE Email Setup.
- [x] **14.6 / Gap 125 (code + live verify):** Staff notify via SendGrid — `submitted_by_email`, process-complete + auditor `notify_emails[]`, FE multi-select. Live SendGrid Mail Send verified with `SG.qiVVj3h6T8aZj-vAVV5_9Q...` (2026-08-26).
- [x] **14.8 / Gap 124 (public URL):** Website mailintegration relay (2026-08-10).
- [x] **Gap 124 items 5–7 (hardening):** shared-secret authenticity, 25 MiB cap, dropped-mail table + Admin list (2026-08-12).
- [x] **Gap 124 items 1–4 (live production deployment completed 2026-08-26):**
  - GoDaddy MX record: `inbound.invoicellm.admsofttech.com` ➔ `mx.sendgrid.net` (Priority 10).
  - Subdomain CNAME: `invoicellm.admsofttech.com` ➔ `invoiceeq-fd-endpoint.azurefd.net`.
  - Outbound CNAMEs: `em2270.outbound.invoicellm`, `s1._domainkey.outbound.invoicellm`, `s2._domainkey.outbound.invoicellm`.
  - SendGrid Inbound Parse Webhook: Host `inbound.invoicellm.admsofttech.com` pointing to `https://invoicellm.admsofttech.com/api/v1/email/mailintegration?key=AdmInvoiceSecret2026`.
  - Live E2E runs executed: Inbound webhook multipart verification (HTTP 200) and live outbound dispatch (HTTP 202, Message ID `LbvTNInKRuafc7A2jHXORw`).

### Verification
Unit tests for send helper + confirm-send/resolve with `notify_emails`.
Gap 124 hardening: 12 tests in `tests/test_email_ingestion.py` — reject with no
secret / wrong secret / unconfigured secret; accept across all five secret
transports (parametrised); 413 on an oversized declared `Content-Length` and on
a chunked body with none; malformed/no-PDF/quota drops recorded; Admin list
returns attributed + domain-matched rows and hides unrelated ones; non-Admin is
refused. Website e2e: `email-mailintegration-relay.spec.ts` (unreachable-backend
502).

**Live Verification (2026-08-26):**
- Outbound Mail Send via SendGrid v3 API (`POST /v3/mail/send`): `HTTP 202 Accepted`, Message IDs `57vFoWwrQNigJJLGWPBrGw`, `sDogeDxOS_qCKTW0lKbt8w`, `LbvTNInKRuafc7A2jHXORw`. Zero active bounces.
- Inbound Webhook (`POST /api/v1/email/mailintegration?key=AdmInvoiceSecret2026`): `HTTP 200 OK`, multipart PDF attachment parsed, unknown sender security quarantine verified.
- Microsoft 365 Outlook compatibility: Root `@` MX (`admsofttech-com.mail.protection.outlook.com`) unaffected; `invoice@admsofttech.com` established as human alias to `sbanerji@admsofttech.com`.
