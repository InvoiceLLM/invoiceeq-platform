# Third-Party Integrations & Credentials Setup Guide (Stripe, Clerk, Google, Salesforce)

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

## 2. Stripe Billing & Subscription Setup

Stripe manages plans (Free, Pro, and Combined Pro), invoice quotas, and customer checkout portals.

### Setup Steps:
1. **Register/Login**: Create a company account on the [Stripe Dashboard](https://dashboard.stripe.com/).
2. **Generate API Key**: Go to **Developers** > **API Keys** and copy the **Secret key** (starts with `sk_live_` or `sk_test_`).
3. **Create Products and Prices**:
   * Navigate to **Product Catalog** > **Add Product** and create your plans:
     * **Combined Pro**: Plan price configured at ₹8,999/month.
     * **Pro**: Inbound-only or basic tier plan.
     * Copy the generated **Price IDs** (starts with `price_...`) to configure in your billing logic.
4. **Webhook Setup (Syncing Subscriptions)**:
   * Go to **Developers** > **Webhooks** > **Add Endpoint**.
   * Set the URL to your production endpoint: `https://<backend-domain>/api/v1/billing/webhook`.
   * Under **Select Events**, subscribe to:
     * `customer.subscription.created`
     * `customer.subscription.updated`
     * `customer.subscription.deleted`
     * `checkout.session.completed`
   * Save the endpoint and copy the **Signing Secret** (starts with `whsec_...`).
5. **Customer Portal**:
   * Go to **Settings** > **Customer Portal** and customize branding. Enable features allowing users to cancel or upgrade/downgrade their plans.

---

## 3. Google Drive & Salesforce Connectors Setup

Connectors allow tenants to import/export documents to their workspace Google Drive or Salesforce files.

### Google Drive Setup:
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Go to **APIs & Services** > **OAuth consent screen** (configure as External, add `.../auth/drive.readonly` scope).
3. Under **Credentials** > **Create Credentials** > **OAuth client ID** (Web application).
4. Set Authorized Redirect URI to:
   `https://<backend-domain>/api/v1/connectors/callback/google_drive`
5. Copy the **Client ID** and **Client Secret**.

### Salesforce Connected App Setup:
1. Log in to your Salesforce Org, go to **Setup** > **App Manager** > **New Connected App**.
2. Check **Enable OAuth Settings**.
3. Set Callback URL to:
   `https://<backend-domain>/api/v1/connectors/callback/salesforce`
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
    "stripeSecretKey": { "value": "sk_live_stripeSecret..." },
    "stripeWebhookSecret": { "value": "whsec_..." },
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
