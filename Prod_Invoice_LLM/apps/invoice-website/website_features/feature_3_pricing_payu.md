# Feature Website 3: Pricing Table & PayU Checkout Integration

Build the pricing tables and submit users into PayU's hosted checkout flow for plan payments; the backend's success/failure handlers lock/unlock accounts based on the outcome.

### Theme & Styling Specifications
* Free Card: Transparent slate border (`border-[#222D3D] hover:border-slate-700`).
* Pro Card (Most Popular): Neon purple shadow and border (`border-indigo-600 shadow-[0_0_20px_rgba(99,102,241,0.3)]`).
* Pricing Badges: Pro plan indicator (`bg-indigo-600 text-white rounded-full px-2 py-0.5 text-xs`).

### File Coordinates
* Component: [apps/invoice-website/components/marketing/PricingTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/components/marketing/PricingTable.tsx)
* PayU Router: [apps/invoice-be/routers/billing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/billing.py)

### Tasks
- [ ] **Task 3.1: Build Pricing Cards Layout**
  - Implement two pricing plans:
    - **FREE**: `₹0 / month` - 50 invoices/month, Dashboard + Ingest + Auditor, 1 user limit.
    - **PRO**: `₹4,999 / month` - Unlimited invoices, All screens, Up to 10 users, ERP connectors.
- [ ] **Task 3.2: Connect PayU Checkout Form**
  - Set up a Next.js action on the "Start Pro Trial" button calling backend route `/api/v1/billing/create-checkout-session`.
  - Backend returns hash-signed form fields (`key`, `txnid`, `amount`, `productinfo`, `hash`, `surl`, `furl`, `action_url`).
  - Frontend renders a hidden form with those fields and submits it — this is a **full-page redirect** to PayU's hosted payment page, not a JS overlay (unlike Stripe/Razorpay's Checkout widget models considered earlier).
- [ ] **Task 3.3: Implement PayU Success/Failure Result Pages**
  - `surl`/`furl` point at backend routes (`/api/v1/billing/payu/success`, `/api/v1/billing/payu/failure`), which verify the transaction (response hash + `verify_payment` API cross-check) and then redirect the browser to a friendly website result page (e.g. `/billing/success`, `/billing/failed`) — the website itself never receives or trusts PayU's raw POST directly.
- [ ] **Task 3.4: Implement past-due lockouts**
  - Ensure the auth middleware (`get_tenant_context()`) raises a `402 Payment Required` exception if tenant's status is `'unpaid'`, blocking all API operations.

### Verification Plan
* **Automated Tests**: Mock PayU response hashes and `verify_payment` responses in `pytest`, verifying that only a fully-verified success updates `billing_plan`, and that a lapsed renewal locks the tenant.
* **Manual Verification**: Submit a real sandbox checkout end-to-end using PayU's test card details (already confirmed reachable and hash-valid against the real PayU test environment — see `feature_11_billing.md`), and confirm the frontend correctly reflects the resulting plan/lockout state.
