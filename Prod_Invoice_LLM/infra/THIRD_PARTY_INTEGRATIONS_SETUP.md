# Third-Party Integrations & Credentials Setup Guide (PayU, Clerk, Google, ~~Salesforce~~, SendGrid)

> **⚠️ Salesforce — removed 2026-08-28, see Gap 334 (BE) / Gap 322 (FE). Do not perform the
> Salesforce setup steps in this guide.** They are struck through below and kept only as
> historical record. Two independent causes: (1) the OAuth app is a Salesforce **External Client
> App** with **Distribution State = Local**, which structurally blocks cross-org OAuth — confirmed
> live against `ca-invoice-be-dev` with Salesforce's own `OAUTH_AUTHORIZATION_BLOCKED — Cross-org
> OAuth flows are not supported for this external client app`. No setting fixes this, and
> Salesforce also stopped allowing new classic Connected Apps as of **Spring '26** without a
> support exception. (2) Wrong data model — the connector browsed Salesforce **Libraries**
> (`ContentWorkspace`), but real invoices live on **Account/Opportunity** records.
>
> **The `infra/` side was deliberately NOT cleaned up** (out of Gap 334's scope): the
> `SALESFORCE-CLIENT-SECRET` Key Vault secret, the `salesforceClientSecret` params entry, and the
> `SALESFORCE_*` container env vars still exist in bicep and still deploy. They are inert — no
> backend code reads them any more. Removing them is a separate, founder-gated change; an unused
> env var is harmless, a deleted Key Vault secret is not trivially reversible.

This document describes how to configure the official company credentials for all third-party integrations (Authentication, Billing, Storage Connectors, and Email) in your production Azure deployments using the Bicep infrastructure configuration.

---

## 1. Clerk Authentication Setup

Clerk manages user authentication, role assignment, and multi-tenant profiles.

### Setup Steps:
1. **Register/Login**: Create a company account on the [Clerk Dashboard](https://dashboard.clerk.com/).
2. **Create Application**: Choose **Multi-tenant / Organization** active patterns.
3. **Get API Keys**: Go to **API Keys** and copy:
   * **Publishable Key**: Used by the frontend Container App (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`).
   * **Secret Key**: Used by the backend Container App (`CLERK_SECRET_KEY`).
4. **JWT Templates (Scoping)**:
   * Go to **JWT Templates** > **New Template** > **FastAPI / Custom**.
   * Add claims for `tenant_id` and `role` under the user metadata payload so the backend can automatically parse tenant scopes from incoming request headers.
   * Copy the **Issuer URL** and **JWKS URL** shown for this template — the backend needs these to verify incoming session tokens: `CLERK_JWT_ISSUER` and `CLERK_JWKS_URL` (`apps/invoice-be/config.py`). Not yet wired into the Bicep/Key Vault setup — add alongside `CLERK_SECRET_KEY` in `05-secrets.bicep` when the auth work lands.
5. **Redirect Configurations**:
   * Set your sign-in, sign-up, and dashboard redirects matching your production domain:
     * Sign-in: `https://<frontend-domain>/sign-in`
     * Sign-up: `https://<frontend-domain>/sign-up`
     * Post-Auth Redirect: `https://<frontend-domain>/dashboard`
   * (Exact route names are pending the `auth-feature-4` reconciliation — current in-repo routes are `/login`/`/admin/login`/`/admin/signup`, not `/sign-in`/`/sign-up`; update this once finalized.)

> **Container Apps deployment note:** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is a Next.js client-side variable — it's inlined into the JS bundle at `next build` time, not read at container runtime. The current `invoice-fe.bicep` sets it as a plain Container App environment variable, which has **no effect** on the deployed app's actual client bundle. It must instead be passed as a Docker `--build-arg` when building the image (`az acr build --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=...`), with the Dockerfile declaring `ARG`/`ENV` before its `RUN npm run build` step. Same applies to `invoice-website` once its Dockerfile exists.

---

## 2. PayU Billing Setup

PayU manages plans (Free, Pro, and Combined Pro), invoice quotas, and customer checkout. Chosen after Razorpay's signup also turned out to require PAN even for basic account creation (not just for going live) — PayU's **classic hash-based integration** was selected specifically because it ships publicly-documented sandbox test credentials that work without any account at all, letting the integration be built and verified before KYC is done.

### Setup Steps (verified working end-to-end, 2026-07-31):
1. **Register/Login**: Create an account on the [PayU Dashboard](https://onboarding.payu.in/). Business Type **"Individual"** or **"Proprietorship"** accepts your own personal PAN — no registered company/GST needed to get started. Bank account + full KYC is only required later, to move from test to live mode.
2. **Get Merchant Key + Salt**: After login, go to your account/profile menu → **Settings** → **Payment Gateway** / **Integration Details**. Copy the **Merchant Key** and the **Salt** (PayU issues two salt versions — v1/SHA256 legacy, v2/SHA512 current; use the **v2/SHA512** salt).
3. **Confirm the environment (Test vs Live)**: there's a Test/Live toggle near the top of the dashboard — Key/Salt differ per environment. Pre-KYC, only Test-mode keys are active.
4. **Verify the credentials work** (no code needed — pure `curl`):
   ```bash
   TXNID="conn_test_$(date +%s)"
   HASH=$(printf '%s' "${MERCHANT_KEY}|verify_payment|${TXNID}|${SALT}" | openssl dgst -sha512 -hex | sed 's/^.* //')
   curl -s -X POST "https://test.payu.in/merchant/postservice.php?form=2" \
     --data-urlencode "key=${MERCHANT_KEY}" \
     --data-urlencode "command=verify_payment" \
     --data-urlencode "var1=${TXNID}" \
     --data-urlencode "hash=${HASH}"
   ```
   A response like `{"status":0,"msg":"...Fetched Successfully",...}` (even reporting the fake txnid as "Not Found") confirms the key/salt pair authenticates correctly — an invalid pair gets rejected outright instead.
5. **No webhook registration needed** — PayU's classic flow doesn't use dashboard-configured webhooks. Payment confirmation happens via `surl`/`furl` (success/failure return URLs) that your backend passes on every checkout request, POSTed to directly by PayU after payment completes. See `feature_11_billing.md` for the response-hash + `verify_payment` server-to-server cross-check pattern used to trust that POST.
6. **Checkout Integration Note**: PayU Checkout is a **full-page redirect** to PayU's hosted payment page (`test.payu.in/_payment` / `secure.payu.in/_payment`), not a client-side JS overlay — the frontend renders a hidden auto-submitting HTML form with the backend's hash-signed fields. No customer-portal-style self-service upgrade/cancel UI exists; the classic API is also **one-time-payment only** (no native recurring/subscription object) — this MVP re-runs the checkout flow each billing cycle rather than auto-debiting, see `feature_11_billing.md`'s renewal-model note.

---

## 3. Google Drive ~~& Salesforce~~ Connectors Setup

Connectors allow tenants to import/export documents to their workspace Google Drive files.
(~~or Salesforce~~ — removed 2026-08-28, Gap 334.)

### Google Drive Setup:
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Go to **APIs & Services** > **OAuth consent screen** (configure as External, add `.../auth/drive.readonly` scope).
3. Under **Credentials** > **Create Credentials** > **OAuth client ID** (Web application).
4. Set Authorized Redirect URI to:
   `https://<frontend-domain>/api/connectors/callback/google_drive`
5. Copy the **Client ID** and **Client Secret**.

### ~~Salesforce Connected App Setup:~~ — REMOVED 2026-08-28 (Gap 334), DO NOT PERFORM

> These steps cannot succeed and must not be followed. Creating a new classic Connected App has
> been blocked by Salesforce since Spring '26 without a support exception, and the existing
> External Client App structurally refuses cross-org OAuth. Kept struck through as the historical
> record of what was configured.

1. ~~Log in to your Salesforce Org, go to **Setup** > **App Manager** > **New Connected App**.~~
2. ~~Check **Enable OAuth Settings**.~~
3. ~~Set Callback URL to `https://<frontend-domain>/api/connectors/callback/salesforce`~~
4. ~~Under Selected OAuth Scopes, add `Access and manage your data (api)` and `Perform requests at any time (refresh_token, offline_access)`.~~
5. ~~Save and copy the **Consumer Key** (Client ID) and **Consumer Secret** (Client Secret).~~

---

## 4. SendGrid Email (Inbound Parse + Mail Send) — Gap 124 leftovers

Inbound PDF receive and staff notify both use SendGrid. BE ingress is internal-only; **public** webhook is on `invoice-website`.

### Receive (Inbound Parse)
1. **GoDaddy (or DNS host):** point MX for `EMAIL_APP_DOMAIN` / `invoiceeq.app` at SendGrid’s inbound MX records (per SendGrid Inbound Parse docs).
2. **SendGrid → Settings → Inbound Parse:** add a host for that domain.
3. **Destination URL** (must be the **website** FQDN, not BE):
   `https://ca-invoice-website-<env>.<caeDomain>/api/v1/email/mailintegration`
   Website route relays raw multipart to internal BE (`apps/invoice-website/app/api/v1/email/mailintegration/route.ts`). Do **not** use `/api/email/*` (Multi-Zone FE settings proxy).
4. Optional: check “POST the raw, full MIME message” only if you change BE parsing — current BE expects SendGrid’s multipart `to`/`from` + file fields.
5. **Seed `SENDGRID-INBOUND-SECRET` in Key Vault — now REQUIRED, not optional.** As of 2026-08-12 (Gap 124 item 5) the BE verifies this secret on every inbound POST and is **fail-closed**: an empty value rejects *all* mail with 401, it does not disable the check. Pick any long random string, seed it as `SENDGRID-INBOUND-SECRET` (param already in `05-secrets.bicep`; `invoice-be.bicep` maps it to env `INBOUND_PARSE_SHARED_SECRET`), then put it in the Destination URL from step 3 as a query parameter:
   `https://ca-invoice-website-<env>.<caeDomain>/api/v1/email/mailintegration?key=<the-secret>`
   The website relay forwards the query string and the `Authorization` / `X-Inbound-Secret` headers through to the BE. Basic credentials in the URL (`https://sendgrid:<secret>@…`) work too — only the password half is compared. Rejections are recorded and visible in the app's **Admin console → Dropped inbound emails**, so a wrong/missing secret shows up there rather than silently eating mail.
6. Attachments are capped at 25 MiB per POST (`INBOUND_EMAIL_MAX_BYTES`, enforced at both the website relay and the BE); oversized mail is rejected with 413 and also listed in that Admin panel.

### Send (Mail Send / Gap 125)
1. Create a SendGrid API key with Mail Send; seed as `SENDGRID-API-KEY` (already wired in bicep/KV).
2. Single Sender Verification is enough to call the API; **domain authentication** (DNS CNAMEs on GoDaddy) improves inbox placement.

### Live check
Registered From → `invoices@invoiceeq.app` → Parse → website relay → BE → invoice row. Tracked as Gap 124 E2E.

---

## 6. Custom Domain (Azure Front Door + WAF) — Website Gap 185

Binds a real purchased domain (e.g. `invoiceeq.app`) to `invoice-website` via Azure Front Door, per `feature_6_custom_domain_integration.md`. Additive to the DNS records in section 4 above (SendGrid MX/domain-auth) — same registrar, different record set, do not remove those.

### Step 1: Deploy Front Door with the domain param set, before touching DNS
`deploy-all.ps1` doesn't take custom-domain as a script flag — it reads bicep params from your environment's `infra/params.<env>.json` (see section 5 below). Add `customDomainName` there alongside the other optional string params (e.g. next to `sendgridSendingDomain`):
```json
"customDomainName": { "value": "invoiceeq.app" }
```
Then run the standard deploy:
```powershell
./infra/deploy-all.ps1 -Environment prod -ResourceGroup rg-invoice-prod -Location centralus -NamingPrefix company
```
This deploys the Front Door profile, endpoint, origin, route, and WAF policy successfully even before DNS exists — only the custom-domain binding itself sits in a pending-validation state until the records below are added. Read the deployment outputs `frontDoorDomainValidationToken` and `frontDoorEndpointHostName` — you need both for the next step (`az deployment group show --resource-group <rg> --name <stage8-deployment-name> --query properties.outputs`).

### Step 2: GoDaddy — Azure domain verification + routing
1. **TXT record** at `_dnsauth.<your-domain>` (or `_dnsauth.<subdomain>` if binding a subdomain) = the `frontDoorDomainValidationToken` value from Step 1.
2. **CNAME record** for the domain/subdomain → the `frontDoorEndpointHostName` value from Step 1 (looks like `<endpoint>.z01.azurefd.net`). If binding the bare apex domain (`invoiceeq.app` with no subdomain), GoDaddy doesn't support a CNAME at the apex — use GoDaddy's ALIAS/forwarding record type instead, or bind a subdomain (`www.invoiceeq.app` or `app.invoiceeq.app`) and redirect the apex to it.
3. Wait for propagation and Azure's automatic validation (minutes to a few hours) — check the custom domain's status in the Azure Portal (Front Door profile → Domains) until it reads **Approved**, at which point Front Door auto-issues the managed TLS certificate. No manual certificate upload needed.

### Step 3: Clerk — cut over to a production instance on the real domain
The current Clerk instance is a **test** instance (`pk_test`/`sk_test`). A real custom domain is also the natural point to cut over to production:
1. In the Clerk Dashboard, add your domain under **Domains** and switch (or create) a **Production** instance bound to it.
2. Clerk generates its own required DNS records (typically `accounts.<domain>`, `clerk.<domain>`, and DKIM CNAMEs for its email sending) — add all of them at GoDaddy. These are separate from and additive to the Azure verification records in Step 2.
3. Once Clerk confirms the domain, copy the **production** Publishable Key and Secret Key, and update `nextPublicClerkPublishableKey`/`clerk-secret-secret` (Key Vault) for this environment, replacing the test keys. Re-deploy so the new build-arg-injected publishable key reaches the client bundle (see section 1's Container Apps deployment note above — this still applies).

### Step 4: Google Drive ~~/ Salesforce~~ — update redirect URIs
Bicep already switches `GOOGLE_REDIRECT_URI` (~~and `SALESFORCE_REDIRECT_URI`, now inert~~) to the custom domain automatically once `customDomainName` is set (see `feature_6_custom_domain_integration.md`). The third-party dashboard still needs a manual matching update, same as Gap 131's original setup:
1. Google Cloud Console → your OAuth client → Authorized redirect URIs → add `https://<domain>/api/connectors/callback/google_drive`.
2. ~~Salesforce → Connected App → Callback URL → add `https://<domain>/api/connectors/callback/salesforce`.~~ **— struck 2026-08-28 (Gap 334): no Salesforce Connected App exists to update. This is no longer a pending cutover task.**
3. Leave the old CAE-FQDN redirect URIs registered too until you've confirmed the new domain works end-to-end, then remove them.

### Live check
`https://<domain>` returns the real site over a valid (non-self-signed) certificate; login completes through Clerk's production instance; `/contact` submits successfully; a burst of >20 requests to `/api/contact` inside 5 minutes gets WAF-blocked (confirms the Gap 249 edge-mitigation rule is active — the endpoint itself is still unauthenticated and unpatched for the email-injection issue, Gap 250, which this domain work does not address).

---

## 5. Key Vault Seeding & Bicep Orchestration

All secrets must be stored securely inside **Azure Key Vault** and injected into Container Apps at deploy time.

### Step 1: Update Parameter Secret JSON
Add the credentials directly to your local, Git-ignored `infra/params.<env>.secrets.json` file:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "dbAdminPassword": { "value": "..." },
    "clerkSecretKey": { "value": "sk_live_clerkSecret..." },
    "tokenEncryptionKey": { "value": "..." },
    "payuMerchantKey": { "value": "..." },
    "payuMerchantSalt": { "value": "..." },
    "googleClientSecret": { "value": "..." },
    "salesforceClientSecret": { "value": "..." },   // inert since Gap 334 (2026-08-28); still required by bicep, read by nothing
    "sendgridApiKey": { "value": "..." },
    "sendgridInboundSecret": { "value": "..." }
  }
}
```

### Step 2: Bicep Deployment
Run the standard orchestrator command. The deploy script automatically reads your parameter secrets, populates Key Vault during Step 5, and binds them to Container App variables in Step 8:
```powershell
./infra/deploy-all.ps1 -Environment prod -ResourceGroup rg-invoice-prod -Location centralus -NamingPrefix company
```
