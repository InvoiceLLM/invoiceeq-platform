# Feature 11: Stripe Billing & Subscriptions API

Implement Stripe checkout subscriptions redirects and integrate webhook event processors to auto-manage tenant plan upgrades, downgrades, and payment lockouts.

### File Coordinates
* Router: [apps/invoice-be/routers/billing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/billing.py) → planned `POST /billing/create-checkout-session` → `create_checkout_session()`, `POST /webhooks/stripe` → `stripe_webhook_handler()`

### Functionality (planned)
* `create_checkout_session()`: Initiates a Stripe Checkout session (`mode="subscription"`). It accepts a target plan parameter (`pro_standard` or `pro_combined`). If upgrading from standard `pro` to `pro_combined`, Stripe computes and processes the prorated difference (additional ₹4,000/month delta) for the current billing cycle.
* `stripe_webhook_handler()`: Verifies `Stripe-Signature` against `STRIPE_WEBHOOK_SECRET`.
  * `checkout.session.completed` / `customer.subscription.updated`: Resolves the tenant ID and updates `Tenant.billing_plan` to either `'pro'` or `'pro_combined'`.
  * `invoice.payment_failed` / `customer.subscription.deleted`: Updates `Tenant.billing_plan = 'unpaid'`.
  * Note: The auth middleware `dependencies.py::get_tenant_context()` already checks for `'unpaid'` and blocks access with a `402 Payment Required` exception.

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
