# Feature 11: Stripe Billing & Subscriptions API

Implement Stripe checkout subscriptions redirects and integrate webhook event processors to auto-manage tenant plan upgrades and payment lockouts.

### File Coordinates
* Router (not yet created — see Gap 14 in `be_features_tracker.md`): [apps/invoice-be/routers/billing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/billing.py) → planned `POST /billing/create-checkout-session` → `create_checkout_session()`, `POST /webhooks/stripe` → `stripe_webhook_handler()`

### Functionality (planned — nothing in this file exists in code yet)
`create_checkout_session()` will initiate a Stripe Checkout session (`mode="subscription"`, the monthly Pro price ID) for the tenant and return the redirect URL to the FE/marketing site. `stripe_webhook_handler()` will verify the `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET`, then branch on event type: `checkout.session.completed` looks up the tenant by Stripe customer ID and sets `Tenant.billing_plan = 'pro'`; `invoice.payment_failed` / `customer.subscription.deleted` set it to `'unpaid'`, which `dependencies.py::get_tenant_context()` (see `feature_1_auth.md`) already checks and blocks on with `402` — that enforcement path exists today even though nothing sets `'unpaid'` yet.

### Tasks
- [ ] **Task 11.1: Code Checkout Session Endpoint**
  - Implement `POST /api/v1/billing/create-checkout-session`.
  - Initiate a Stripe Checkout session using `mode="subscription"` referencing the monthly recurring Pro price ID.
  - Return the Stripe redirected URL back to the frontend website.
- [ ] **Task 11.2: Code Stripe Webhooks Handler**
  - Implement `POST /api/v1/webhooks/stripe` accepting webhooks directly from Stripe.
  - Validate webhook signatures using `STRIPE_WEBHOOK_SECRET`.
- [ ] **Task 11.3: Update Tenant Billing Plans**
  - Handle `checkout.session.completed` event: Locate the customer's matching `tenant_id` and update `billing_plan` to `'pro'` in PostgreSQL.
  - Handle `invoice.payment_failed` and `customer.subscription.deleted` events: Update the tenant's `billing_plan` state to `'unpaid'` in PostgreSQL to activate the block state.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_billing.py` with mock signatures verifying that payment failures update database status correctly.
* **Manual Verification**: Run `stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe` and trigger mock events to verify database updates.
