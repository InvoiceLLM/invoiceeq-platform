# Feature Website 3: Pricing Table & Stripe Checkout Integration

Build the pricing tables, connect users to Stripe checkout sessions for monthly subscriptions, and integrate webhook callbacks to lock/unlock user accounts.

### Theme & Styling Specifications
* Free Card: Transparent slate border (`border-[#222D3D] hover:border-slate-700`).
* Pro Card (Most Popular): Neon purple shadow and border (`border-indigo-600 shadow-[0_0_20px_rgba(99,102,241,0.3)]`).
* Pricing Badges: Pro plan indicator (`bg-indigo-600 text-white rounded-full px-2 py-0.5 text-xs`).

### File Coordinates
* Component: [apps/invoice-website/components/marketing/PricingTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/components/marketing/PricingTable.tsx)
* Stripe Router: [apps/invoice-be/routers/billing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/billing.py)

### Tasks
- [ ] **Task 3.1: Build Pricing Cards Layout**
  - Implement two pricing plans:
    - **FREE**: `₹0 / month` - 50 invoices/month, Dashboard + Ingest + Auditor, 1 user limit.
    - **PRO**: `₹4,999 / month` - Unlimited invoices, All screens, Up to 10 users, ERP connectors.
- [ ] **Task 3.2: Connect Stripe Checkout Session API**
  - Set up a Next.js action button linking the "Start Pro Trial" button to backend route `/api/v1/billing/create-checkout-session`.
  - Configure the backend Stripe session call using `mode: "subscription"` and referencing the recurring monthly Price ID.
- [ ] **Task 3.3: Implement Stripe Webhooks Processing**
  - Create the API route `/api/v1/webhooks/stripe` to handle events:
    - `checkout.session.completed`: Upgrade tenant `billing_plan` to `'pro'`.
    - `invoice.payment_failed` / `customer.subscription.deleted`: Revert/lock tenant by changing `billing_plan` status to `'unpaid'` in the database.
- [ ] **Task 3.4: Implement past-due lockouts**
  - Ensure the auth middleware (`get_tenant_context()`) raises a `402 Payment Required` exception if tenant's status is `'unpaid'`, blocking all API operations.

### Verification Plan
* **Automated Tests**: Mock Stripe webhook signatures in `pytest` verifying that `payment_failed` webhook locks the tenant.
* **Manual Verification**: Run Stripe local CLI (`stripe trigger invoice.payment_failed`) to simulate subscription payments failure, and confirm the frontend dashboard blocks interaction.
