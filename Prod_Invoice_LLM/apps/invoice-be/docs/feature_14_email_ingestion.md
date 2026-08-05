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

### SendGrid setup — one-time, platform-wide (not yet done in any environment)
Both directions above ride on the same SendGrid account. Configured **once
for the whole platform**, not once per tenant — unlike `feature_9_connectors.md`'s
Google/Salesforce connectors where each *end-user* connects their own
account. Every tenant's inbound alias is the same domain
(`invoices.invoice-ai.com`) with a different UUID as the local part;
SendGrid's Inbound Parse is a wildcard on that whole domain, forwarding
*any* local part to the one webhook above — our own backend, not
SendGrid, resolves which tenant an email belongs to
(`UUID_EMAIL_PATTERN` parse of the `To` header). Outbound (Task 14.6,
below) works the same way: one platform-authenticated sending domain,
with a tenant's saved `outbound_sender_email` used only as the `Reply-To`
header, never as a per-tenant SendGrid identity — see `be_features_tracker.md`
Gap 125 items 2/5 for why this design was chosen over per-tenant domain
authentication (avoids requiring every tenant to run their own SPF/DKIM/
DMARC DNS setup).

**Dashboard steps:**
1. Create/confirm the SendGrid account.
2. **Sender Authentication → Authenticate a Domain** — enter the
   platform's domain (e.g. `invoice-ai.com`, or a dedicated subdomain
   like `mail.invoice-ai.com` for outbound specifically, kept separate
   from the inbound-receiving subdomain). SendGrid returns a set of CNAME
   records.
3. Add those CNAME records at whichever DNS provider actually hosts
   `invoice-ai.com` — **not Azure**: this infra has no DNS zone resource
   anywhere, so this is a manual step at the domain registrar/DNS host,
   outside this repo entirely.
4. Back in SendGrid, click **Verify** on the domain once the records
   propagate.
5. **Settings → Inbound Parse → Add Host & URL** — hostname
   `invoices.invoice-ai.com`, destination URL **must be the public
   website's proxied path**, not the backend directly — `invoice-be`'s
   ingress is `external: false` (see `be_features_tracker.md` Gap 124
   item 1, found 2026-08-05: same root cause as Gap 131's connector
   `redirect_uri_mismatch`, since `invoice-website` is the only
   `external: true` app in this infra). The correct destination is
   `https://<WEBSITE_PUBLIC_URL>/api/email/inbound`, which requires a new
   FE proxy route (`app/api/email/inbound/route.ts`, Clerk-auth-bypassed
   in `middleware.ts`) that doesn't exist yet — **not buildable as a
   direct backend URL today**.
6. Add the **MX record** SendGrid shows for that hostname
   (`mx.sendgrid.net`, priority 10) at the same DNS host as step 3.
7. **Settings → API Keys → Create API Key**, Mail Send permission (needed
   once Task 14.6 builds outbound) — copy the key value; SendGrid shows
   it exactly once.

**What to save, and where:**
| Value | Where it's saved | Secret? |
|---|---|---|
| SendGrid API Key (step 7) | Azure Key Vault secret `SENDGRID-API-KEY` → `invoice-be` container env `SENDGRID_API_KEY` | Yes |
| Inbound Parse shared secret (Gap 124 item 2's fix — a value only this app and the registered webhook URL know, to confirm a request genuinely came from SendGrid) | Azure Key Vault secret `SENDGRID-INBOUND-SECRET` → env `INBOUND_PARSE_SHARED_SECRET` | Yes |
| Authenticated sending domain name (e.g. `mail.invoice-ai.com`) | Plain bicep param, not Key Vault — not sensitive, same treatment as `googleRedirectUri` in `feature_9_connectors.md` | No |
| Inbound receiving domain name (e.g. `invoices.invoice-ai.com`) | Hardcoded in `app/settings/email/page.tsx`'s `platformDomain` constant — matches the domain-level (not per-tenant) design | No |
| Anything tenant-specific | **Nothing** — a tenant's alias/sender-email are both derived from data already stored (their `tenant_id`, their saved `outbound_sender_email`), never round-tripped through SendGrid's own API for storage | N/A |

**Bicep — done 2026-08-05**, mirroring the pattern already used for
`GOOGLE-CLIENT-SECRET`/`SALESFORCE-CLIENT-SECRET`: `infra/05-secrets.bicep`
(`sendgridApiKey`/`sendgridInboundSecret` secure params → 2 Key Vault
secret resources), `infra/modules/compute/invoice-be.bicep`
(`sendgridSendingDomain` param, 2 `secrets:` entries, 3 `env:` entries),
`infra/08-apps.bicep` (`sendgridSendingDomain` param threaded to the
`backendApp` module), `infra/params.dev.json` (`sendgridSendingDomain`
entry), `infra/params.dev.secrets.json.example` (placeholder entries for
both secrets). Real values still need seeding into `params.dev.secrets.json`
(gitignored, local-only) once a real SendGrid account exists.
