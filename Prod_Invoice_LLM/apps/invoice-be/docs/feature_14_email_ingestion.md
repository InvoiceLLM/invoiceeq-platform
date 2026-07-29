# Feature 14: Email-Based Invoice Ingestion & Outbound Delivery

Symmetric email capability:
1. **Inbound Email Ingestion**: Accept invoices sent directly to a per-tenant inbound email alias (forward/CC invoices to a fixed address). **Implemented 2026-07-28.**
2. **Outbound Email Delivery**: Send verified outbound invoices automatically to customer emails via the tenant's configured outbound sender email. **Not implemented** — no send-side code exists yet; only the inbound direction was built.

### Decision point — RESOLVED 2026-07-28: SendGrid Inbound Parse selected
**Azure Communication Services Email vs. SendGrid Inbound Parse** for
receiving inbound mail — **SendGrid Inbound Parse won**: mature, POSTs a
fully-parsed multipart payload (`to`/`from` form fields + file attachments)
directly to a webhook URL, less plumbing on our side than ACS Email's less
mature inbound routing. `routers/email_ingestion.py::inbound_email_webhook()`
is built against exactly that SendGrid POST shape.
**Caveat**: the endpoint does **not** currently verify SendGrid's request
signature (no `Authorization`/signature-header check) — this was
identified and explicitly deferred as a separate, tracked follow-up (see
`be_features_tracker.md`), not part of this documentation pass. It is a
real open security gap, not a doc error.

### File Coordinates
* Upload endpoint (reused via shared helper): [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py) → `_ingest_single_file()`
* Inbound webhook + allow-list CRUD: [apps/invoice-be/routers/email_ingestion.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/email_ingestion.py) → `inbound_email_webhook()` (`POST /api/v1/email/inbound`), `list_email_senders()`/`add_email_sender()`/`delete_email_sender()` (`GET/POST/DELETE /api/v1/email/settings/email-senders`)
* Allow-list model: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py) → `TenantEmailSender` (migration `71d18e2c3349`)
* Tests: [apps/invoice-be/tests/test_email_ingestion.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/test_email_ingestion.py) — 5/5 passing (CRUD allow-list, invalid/unknown alias 404s, unauthorized-sender silent drop, PDF happy path)

### Functionality (as implemented)
Each tenant's inbound alias is `{tenant_id}@invoices.{platform-domain}` —
the UUID is pulled straight out of the `To` header via
`UUID_EMAIL_PATTERN`, no new alias-storage field needed. `POST
/api/v1/email/inbound` is **not tenant-authenticated** (no logged-in
user; this is SendGrid posting to us) and is not yet signature-verified
(see caveat above). The handler: (1) resolves `tenant_id` from the `To`
header, 404s on a missing/invalid alias or unknown tenant; (2) checks the
`From` address (bracket-stripped, lowercased) against that tenant's
`TenantEmailSender` allow-list — an unauthorized sender gets a `200 OK`
`{"status": "dropped"}` response with **no processing** (fixed response
either way, avoiding leaking which senders are allowed); (3) filters
attachments to `.pdf` only (a mail with no PDF attachments returns
`{"status": "skipped"}`, still `200 OK`); (4) for each PDF, calls
`routers/invoices.py::_ingest_single_file()` — the same shared per-file
ingestion helper the authenticated multipart upload endpoint uses — under
a synthetic `TenantContext(user_id="system_email_ingestion", role="System")`,
enforcing the tenant's free-plan quota (`free_invoices_remaining`) exactly
like a normal upload, and tagging each resulting `Invoice` row `["email"]`.

### Tasks
- [x] **Task 14.1: Vendor decision + provider account setup** — SendGrid
      Inbound Parse selected (see decision point above). DNS/MX
      registration for `invoices.{platform-domain}` against a real
      SendGrid account is an infra step, not yet done outside this repo —
      the webhook code itself is complete and tested.
- [x] **Task 14.2: Shared per-file ingestion helper** — `routers/invoices.py::_ingest_single_file()`
      is the shared helper both the multipart upload endpoint and the
      email webhook call (built as a per-file helper rather than the
      originally-planned batch `_ingest_invoice_files()` signature — same
      goal, one implementation, no duplicated validation/blob/queue logic).
- [x] **Task 14.3: `TenantEmailSender` allow-list model + management endpoints**
      — `GET/POST/DELETE /api/v1/email/settings/email-senders`, tenant-scoped.
      (Note: lives under `/api/v1/email/settings/...`, not
      `/api/v1/settings/email-senders` as originally sketched.)
- [x] **Task 14.4: Inbound webhook endpoint** — `POST /api/v1/email/inbound`,
      tenant resolution via alias, sender allow-list check, PDF attachment
      extraction, dispatch via Task 14.2's shared helper. Provider-signature
      verification is the one piece **not** done — tracked separately, out
      of scope for this doc pass.
- [ ] **Task 14.5: Surface the alias in Settings UI** — FE-side; see the
      frontend's Settings docs (not tracked in this backend doc set).

### Verification Plan
* **Automated Tests**: `uv run pytest tests/test_email_ingestion.py` — 5/5
  passing: allow-list CRUD, unknown-alias 404, invalid-UUID-alias 404,
  disallowed-sender silent-drop (200 + `status: dropped`), PDF-attachment
  happy path landing in the same `Invoice` row shape as a manual upload
  (`status: PROCESSING`, `tags` includes `"email"`).
* **Manual Verification** *(not yet done — no real SendGrid account
  configured in this repo)*: send a real email with a PDF attachment to a
  test tenant's alias, confirm it appears in the ingestion queue exactly
  like a UI upload.
