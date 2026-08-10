# Third-Party Integrations & Credentials Setup Guide (PayU, Clerk, Google, Salesforce)

This document describes how to configure the official company credentials for all third-party integrations (Authentication, Billing, and Storage Connectors) in your production Azure deployments using the Bicep infrastructure configuration.

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

## 3. Google Drive & Salesforce Connectors Setup

Connectors allow tenants to import/export documents to their workspace Google Drive or Salesforce files.

### Google Drive Setup:
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Go to **APIs & Services** > **OAuth consent screen** (configure as External, add `.../auth/drive.readonly` scope).
3. Under **Credentials** > **Create Credentials** > **OAuth client ID** (Web application).
4. Set Authorized Redirect URI to:
   `https://<frontend-domain>/api/connectors/callback/google_drive`
5. Copy the **Client ID** and **Client Secret**.

### Salesforce Connected App Setup:
1. Log in to your Salesforce Org, go to **Setup** > **App Manager** > **New Connected App**.
2. Check **Enable OAuth Settings**.
3. Set Callback URL to:
   `https://<frontend-domain>/api/connectors/callback/salesforce`
4. Under Selected OAuth Scopes, add:
   * `Access and manage your data (api)`
   * `Perform requests at any time (refresh_token, offline_access)`
5. Save and copy the **Consumer Key** (Client ID) and **Consumer Secret** (Client Secret).

---

## 4. Key Vault Seeding & Bicep Orchestration

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
    "salesforceClientSecret": { "value": "..." }
  }
}
```

### Step 2: Bicep Deployment
Run the standard orchestrator command. The deploy script automatically reads your parameter secrets, populates Key Vault during Step 5, and binds them to Container App variables in Step 8:
```powershell
./infra/deploy-all.ps1 -Environment prod -ResourceGroup rg-invoice-prod -Location centralus -NamingPrefix company
```
