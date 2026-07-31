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

2. **PayU Checkout / Upgrade Flow**:
   * PayU's classic hash-based API has **no subscription object to update** and **no built-in proration engine** — unlike Stripe/Razorpay's Subscriptions API, every charge (including an upgrade) is just another one-time `create_checkout_session()` call.
   * **MVP approach**: an upgrade from `pro` to `pro_combined` runs a fresh one-time checkout for the **full ₹8,999** and resets the billing cycle to start today (rather than computing and charging a prorated ₹4,000 delta for the remainder of the old cycle — that math would need to be built entirely in our own backend, since PayU won't do it). This is a deliberate simplification, not a PayU limitation to work around later with more integration — if prorated upgrades matter later, it's our own billing logic to add, independent of the payment gateway.
   * There is no card-vs-UPI branching concern here (unlike the Razorpay design considered earlier) — every PayU checkout, upgrade or otherwise, is the identical hosted-checkout-page flow regardless of which payment method the user picks on PayU's page.

3. **PayU Confirmation**:
   * The upgrade checkout's `surl`/`furl` land on the same `payu_success()`/`payu_failure()` handlers as any other checkout (see `feature_11_billing.md`) — on verified success, `Tenant.billing_plan` is set to `'pro_combined'` and the cycle start date reset.

### Tasks
- [ ] **Task 3.1.1: Add Combined Pro card to Pricing Table**
  - Render the third tier on the pricing page (₹8,999/month, features: Inbound + Outbound, unlimited volume).
- [ ] **Task 3.1.2: Support Upgrade Checkout**
  - "Upgrade" button on the `pro` (standard) plan triggers `create_checkout_session(plan='pro_combined')` for the full ₹8,999 — same endpoint as a fresh signup, no special upgrade-specific API needed.
- [ ] **Task 3.1.3: Confirm Plan Promotion on Success**
  - No separate handler needed — `payu_success()` already promotes `billing_plan` to whatever plan the checkout was created for (see `feature_11_billing.md` Task 11.2/11.3).

### Verification Plan
* **Manual Verification**:
  * Verify the upgrade checkout charges the full ₹8,999 (not a prorated delta) and completes through PayU's real hosted page.
  * Verify that a successful upgrade updates the database field `billing_plan` to `'pro_combined'` and resets the cycle start date.
