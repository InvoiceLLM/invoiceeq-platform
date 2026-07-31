# Feature 11: PayU Billing API

Implement PayU's classic hash-based checkout flow and the `surl`/`furl` confirmation handlers to auto-manage tenant plan upgrades and payment lockouts.

Provider decided 2026-07-31: **PayU**, not Stripe or Razorpay. Stripe stopped onboarding new India-domiciled merchants in 2022. Razorpay's signup also gates basic account creation behind PAN (even for test mode). PayU was chosen specifically because it publishes public sandbox test credentials usable with zero account setup, and — once a real account was created (Individual/Proprietorship business type, personal PAN, no GST/company registration needed) — its Merchant Key + Salt pair was **verified working end-to-end against PayU's live test environment on 2026-07-31**: `verify_payment` API call succeeded, the hash-signed checkout form was accepted by PayU's hosted payment page, a test card passed through 3DS2 simulation and OTP entry. The only failure was at final settlement, consistent with the account not yet having KYC/bank details on file — not an integration defect.

### File Coordinates
* Router: [apps/invoice-be/routers/billing.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/billing.py) → `POST /billing/create-checkout-session` → `create_checkout_session()`, `POST /billing/payu/success` → `payu_success()`, `POST /billing/payu/failure` → `payu_failure()`

### Functionality
* `create_checkout_session()`: Accepts a target plan (`pro` or `pro_combined`), generates a `txnid`, and computes the PayU request hash:
  `sha512(key|txnid|amount|productinfo|firstname|email|udf1|udf2|udf3|udf4|udf5|udf6|udf7|udf8|udf9|udf10|salt)` — with `udf1`-`udf10` empty (unused for now; `udf1` is reserved for `tenant_id` if a future field is needed for reconciliation instead of relying solely on `txnid`).
  Returns the full field set (`key`, `txnid`, `amount`, `productinfo`, `firstname`, `email`, `hash`, `surl`, `furl`, `action_url`) for the frontend to render as a hidden auto-submitting form POSTing to PayU's hosted page (`test.payu.in/_payment` or `secure.payu.in/_payment`, selected by `PAYU_MODE`).
* `payu_success()` / `payu_failure()`: PayU POSTs the transaction result directly to these URLs (configured as `surl`/`furl` on each checkout request — there is no dashboard-configured webhook in PayU's classic flow). Because a bare POST to a public URL can be spoofed by anyone, **the response is never trusted on its own**:
  1. Verify the response hash PayU sends back: `sha512(salt|status|udf10|udf9|udf8|udf7|udf6|udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)` (reverse field order of the request hash, with `status` inserted after `salt`).
  2. Cross-check server-to-server via PayU's `verify_payment` API (`command=verify_payment`, `var1=txnid`, its own `sha512(key|verify_payment|txnid|salt)` hash) — this is the same API call already manually verified working against the real PayU sandbox.
  3. Only if both checks agree does the handler update `Tenant.billing_plan` to `'pro'`/`'pro_combined'` and set `Tenant.payu_subscription_id = txnid`.
* **Renewal model**: PayU's classic API is one-time-payment, not a native recurring/subscription object like Stripe or Razorpay. This feature implements **manual monthly re-payment** — the tenant re-runs `create_checkout_session()` each billing cycle (prompted by the app, e.g. an in-app banner near cycle end) rather than true auto-debit. PayU's separate Standing Instruction (SI) product could enable real auto-renewal later; deliberately out of scope until this MVP ships and SI is separately researched.
* Note: The auth middleware `dependencies.py::get_tenant_context()` already checks for `'unpaid'` and blocks access with a `402 Payment Required` exception — this feature only needs to *set* that state (via a lapsed-renewal check, not a webhook-driven cancellation event, since PayU has none), not build the enforcement itself.

### Tasks
- [ ] **Task 11.1: Code Checkout Session Endpoint**
  - Implement `POST /api/v1/billing/create-checkout-session`.
  - Generate `txnid`, compute the request hash, return the signed field set + `action_url` (test/live selected via `PAYU_MODE`).
- [ ] **Task 11.2: Code PayU Success/Failure Handlers**
  - Implement `POST /api/v1/billing/payu/success` and `POST /api/v1/billing/payu/failure`.
  - Verify the response hash; on success, cross-check via `verify_payment` before trusting it.
- [ ] **Task 11.3: Update Tenant Billing Plans**
  - On a verified successful payment: update `billing_plan` to `'pro'`/`'pro_combined'`, set `payu_subscription_id = txnid`, extend the tenant's paid-through date.
  - Add a scheduled/periodic check (not a PayU event, since none exists) that flips `billing_plan = 'unpaid'` once a tenant's paid-through date lapses without a new successful `txnid`.

### Verification Plan
* **Automated Tests**: `uv run pytest tests/test_billing.py` — mock a valid and an invalid response hash, confirm only the valid one updates `billing_plan`; mock `verify_payment` returning "Not Found" and confirm the handler refuses to upgrade the plan on a hash-valid-but-unverifiable transaction.
* **Manual Verification**: Already partially done ahead of code — see the connection test above. Full manual pass once built: submit a real sandbox checkout via the rendered form, complete a test card + OTP, confirm `payu_success()` fires, `verify_payment` cross-check passes, and `billing_plan` updates in Postgres.
