# Feature Website 3.1: Service Flow Pricing Tier — Combined Pro Plan

Decided option: **Option D — Three-Tier Plan Structure (Standard Pro vs. Combined Pro)**.

### Tiers
* **FREE** — ₹0/month, 50 invoices/month, Dashboard + Ingest + Auditor (Inbound only), 1 user.
* **PRO STANDARD** — ₹4,999/month, unlimited invoices (Inbound only), up to 10 users, ERP connectors.
* **PRO COMBINED** — ₹8,999/month, unlimited invoices (Inbound + Outbound), up to 10 users, ERP connectors.

### Functionality

1. **Outbound Activation Gate**:
   * The Admin can only enable the Outbound service (*Send Invoices*) if the tenant's current plan is `pro_combined`.
   * Toggling it on a `free` or `pro` (standard) plan redirects or displays an upgrade modal.

2. **Stripe Checkout / Upgrade Flow**:
   * If a standard `pro` user upgrades to `pro_combined`, a Stripe Checkout session is created targeting the `pro_combined` recurring monthly Price ID.
   * Stripe handles proration automatically: the user is charged the additional amount (₹4,000/month prorated delta) for the remainder of their current billing cycle.

3. **Stripe Webhook**:
   * Stripe triggers `customer.subscription.updated` or `checkout.session.completed` for the new price, updating the database `Tenant.billing_plan = 'pro_combined'`.

### Tasks
- [ ] **Task 3.1.1: Add Combined Pro card to Pricing Table**
  - Render the third tier on the pricing page (₹8,999/month, features: Inbound + Outbound, unlimited volume).
- [ ] **Task 3.1.2: Support Upgrade/Proration Checkout Session**
  - Implement dynamic Checkout creation based on current plan (`free` vs `pro` Standard to `pro_combined` upgrade).
- [ ] **Task 3.1.3: Update Webhook Handler for Plan Promotion**
  - Update `stripe_webhook_handler()` to process `customer.subscription.updated` and promote billing plan to `'pro_combined'`.

### Verification Plan
* **Manual Verification**:
  * Verify checkout upgrades from standard Pro to Combined Pro display the correct prorated delta on Stripe's hosted checkout screen.
  * Verify that a successful checkout updates the database field `billing_plan` to `'pro_combined'`.

