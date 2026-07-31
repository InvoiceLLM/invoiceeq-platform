# Feature Website 3 / 3.1 Test Suite: Pricing Table & PayU Checkout (incl. Combined Pro Upgrade)

Spec sources: [`website_features/feature_3_pricing_payu.md`](../../../apps/invoice-website/website_features/feature_3_pricing_payu.md), [`feature_3.1_vendor_flow_pricing.md`](../../../apps/invoice-website/website_features/feature_3.1_vendor_flow_pricing.md), backend detail in [`apps/invoice-be/docs/feature_11_billing.md`](../../../apps/invoice-be/docs/feature_11_billing.md).

**Status flag — read before running this suite**: as of this writing, `apps/invoice-website` has **no pricing page or `PricingTable.tsx` component** (`website_features_tracker.md` still lists Feature 3's tasks unchecked; the app's own README confirms "No pricing page — no PayU checkout exists yet"). The backend router `apps/invoice-be/routers/billing.py` (`create_checkout_session`, `payu_success`, `payu_failure`) **does exist** and reads as functionally complete, but it's an uncommitted, undocumented-in-tracker addition — `feature_11_billing.md`'s own tasks are still unchecked `[ ]` too. **Sections 2–4 below are therefore testable against the backend today via direct API calls; section 1 (screen alignment) and any true end-to-end website flow cannot be run until the frontend pricing page is built.**

---

## 1. Screen Alignment Check *(blocked — no `PricingTable.tsx` yet; spec'd for when it lands)*

| TC ID | Element | Expected Visual Spec |
|---|---|---|
| TC-WEB3-01 | FREE card | Transparent slate border (`border-[#222D3D] hover:border-slate-700`); `₹0/month`, 50 invoices/month, Dashboard + Ingest + Auditor, 1 user |
| TC-WEB3-02 | PRO STANDARD card (Most Popular) | Neon purple shadow/border (`border-indigo-600 shadow-[0_0_20px_rgba(99,102,241,0.3)]`), Pro badge (`bg-indigo-600 text-white rounded-full px-2 py-0.5 text-xs`); `₹4,999/month`, unlimited invoices (Inbound only), up to 10 users, ERP connectors |
| TC-WEB3-03 | PRO COMBINED card | `₹8,999/month`, Inbound + Outbound, unlimited volume, up to 10 users, ERP connectors (Task 3.1.1) |
| TC-WEB3-04 | Billing toggle | Monthly/annual toggle updates displayed card price text dynamically |

---

## 2. Functionality Check

| TC ID | Action | Expected Behavior |
|---|---|---|
| TC-WEB3-05 | Admin clicks "Start Pro Trial"/"Upgrade" (once wired) → `POST /api/v1/billing/create-checkout-session` `{plan: "pro"|"pro_combined"}` | Returns hash-signed field set (`key`, `txnid`, `amount`, `productinfo`, `firstname`, `email`, `phone`, `hash`, `surl`, `furl`, `action_url`, `udf1`); frontend renders a hidden auto-submitting form POSTing to `action_url` — a full-page redirect to PayU's hosted page, not a JS overlay |
| TC-WEB3-06 | Non-admin (`context.role != "Admin"`) calls `create_checkout_session` | `403 Forbidden`, "Only Admin users can manage billing." — verify the frontend surfaces this rather than failing silently |
| TC-WEB3-07 | Admin on `pro` (standard) clicks "Upgrade" | Same endpoint, `plan="pro_combined"` — charges the **full** ₹8,999, no prorated delta computed (Task 3.1.2, deliberate MVP simplification) |
| TC-WEB3-08 | PayU POSTs to `surl` (`payu_success`) with a valid, verifiable success | `_handle_payu_callback`: response-hash check (`hmac.compare_digest` vs `_response_hash()`) passes → `_verify_payment_with_payu()` cross-check passes → redirect to `{FRONTEND_URL}/billing/success?plan={plan}` |
| TC-WEB3-09 | PayU POSTs to `furl` (`payu_failure`) | `_handle_payu_callback(is_surl=False)` — always redirects to `{FRONTEND_URL}/billing/failed?txnid={txnid}` regardless of the hash outcome |
| TC-WEB3-10 | Callback POST with no `txnid` | Redirect to `/billing/failed?reason=malformed`, no downstream processing |
| TC-WEB3-11 | Callback with tampered/spoofed `hash` | Redirect to `/billing/failed?reason=hash_mismatch` |
| TC-WEB3-12 | Hash-valid callback, but `_verify_payment_with_payu()` can't reach PayU / finds nothing | Redirect to `/billing/failed?reason=unverifiable` |
| TC-WEB3-13 | Hash-valid + verified, but `productinfo` doesn't map to a known plan | Redirect to `/billing/failed?reason=unknown_plan` |
| TC-WEB3-14 | Hash-valid + verified, but `udf1` isn't a valid tenant UUID, or that tenant no longer exists | Redirect to `/billing/failed?reason=unknown_tenant` |
| TC-WEB3-15 | Tenant with `billing_plan == 'unpaid'` makes any authenticated API call (Task 3.4) | `get_tenant_context()` raises `402 Payment Required` — **verify this check is actually wired**; it's referenced as already existing in `feature_11_billing.md` but confirm in current `dependencies.py` |

---

## 3. Database Validation

| TC ID | Check |
|---|---|
| TC-WEB3-16 | On a fully verified success (TC-WEB3-08): `SELECT billing_plan, payu_subscription_id FROM tenant WHERE id = :tenant_id` — `billing_plan` matches the plan from `productinfo` (`InvoiceAI-{plan}`), `payu_subscription_id` equals the `txnid`. |
| TC-WEB3-17 | Every failure path (TC-WEB3-10 through 14) must leave `Tenant.billing_plan` and `payu_subscription_id` **completely unchanged** — snapshot the row before and after, assert no diff. |
| TC-WEB3-18 | **Idempotency gap to explicitly test**: `_handle_payu_callback` has no check for an already-processed `txnid`. POST the same verified-success callback twice and observe whether the second call re-updates the row (harmless if it just re-sets the same values, but flag if it has any other side effect later). Not currently guarded in the code — this is a probe, not an assumed-pass case. |
| TC-WEB3-19 | Task 11.3's scheduled lapsed-renewal job (flips `billing_plan` to `'unpaid'` once the paid-through date passes with no new successful `txnid`) — confirm this **does not exist** anywhere in the codebase yet (no scheduler/cron referencing `billing_plan`). Track as a known open gap, not a false pass. |

---

## 4. Flow Validation via Log Files

Same caveat as Features 1/2: no file-based logging handler in `invoice-be` — watch stdout/console output.

| TC ID | Trigger | Expected Log Line | Level |
|---|---|---|---|
| TC-WEB3-20 | `create_checkout_session()` succeeds | `"PayU checkout session created: tenant=%s plan=%s txnid=%s amount=%s"` — assert the `txnid` matches the one returned in the response | INFO |
| TC-WEB3-21 | `_verify_payment_with_payu()` HTTP call fails | `"PayU verify_payment call failed for txnid=%s: %s"` | ERROR |
| TC-WEB3-22 | Callback with no `txnid` | `"PayU callback with no txnid, ignoring."` | WARNING |
| TC-WEB3-23 | Callback hash mismatch | `"PayU callback hash mismatch for txnid=%s -- not trusting this POST."` | ERROR |
| TC-WEB3-24 | `verify_payment` unreachable during callback | `"Could not reach PayU verify_payment for txnid=%s -- not trusting this callback."` | ERROR |
| TC-WEB3-25 | Hash-valid but declined/non-success status | `"PayU payment not successful: txnid=%s callback_status=%s verified_status=%s"` — deliberately INFO, not ERROR (a declined card isn't a system fault) | INFO |
| TC-WEB3-26 | Verified success but unknown plan/tenant | `"...productinfo=%r doesn't map to a known plan..."` / `"...udf1=%r isn't a valid tenant_id..."` / `"...tenant %s no longer exists."` | ERROR |
| TC-WEB3-27 | Fully verified success | `"PayU payment verified, tenant=%s upgraded to plan=%s (txnid=%s)."` — this line must correlate 1:1 with the DB mutation in TC-WEB3-16; assert both happen together, never one without the other | INFO |
