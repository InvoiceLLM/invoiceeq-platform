# Feature Website 3.1: Service Flow Pricing Tier — Combined Pro Plan

Decided option: **Option D — Three-Tier Plan Structure (Standard Pro vs. Combined Pro)**.

### Tiers
* **FREE** — ₹0/month, 50 invoices/month, full platform access (Dashboard, Chat, Auditor, Trainer, Connectors), Inbound only, 1 user.
* **PRO STANDARD** — ₹4,999/month, unlimited invoices, same full platform access as Free, Inbound only, up to 10 users.
* **PRO COMBINED** — ₹8,999/month, unlimited invoices, Inbound + Outbound, up to 10 users.

> **Correction, 2026-07-31**: earlier drafts of this doc (and the original pricing page copy) implied Chat/Trainer/Connectors were Pro-exclusive "screens." Checked directly against the code: `routers/chat.py`, `trainer.py`, `connectors.py`, `dashboard.py`, and `audit.py` have **zero** `billing_plan` checks. The only real plan enforcement anywhere in the system is (1) the Free tier's 50-invoice quota and (2) the outbound Send toggle requiring `pro_combined` (`routers/settings.py`, real `402` + a pre-emptive FE upgrade modal in `ServiceFlowToggles.tsx`). So the actual tier differentiators are invoice volume, user count, and outbound access — not feature/screen access. Pricing copy corrected to match reality rather than building new gates to match the old (inaccurate) copy — see `be_features_tracker.md`/`fe_features_tracker.md` if screen-level gating is wanted later; not currently planned.

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
   * **Return flow, built 2026-08-02** (Feature 3 Tasks 3.3/3.5): an upgrading tenant now lands on the same `/billing/success?plan=pro_combined&txnid=…` page as a new subscriber — which names "Pro Combined" and ₹8,999/month explicitly via `lib/billingPlans.ts::PLAN_COPY` — rather than the 404 that was there before. Failures route to `/billing/failed` with the same three-severity treatment. Nothing is upgrade-specific: the upgrade path is the identical `create_checkout_session()` call, so it needed no separate return page. Also as of that date, PayU's callback reaches the backend at all in Azure, via the `app/api/v1/billing/payu/*` pass-through — previously `surl`/`furl` pointed at an internal-only ingress and would never have fired for an upgrade either.
   * "and the cycle start date reset" is **still not literally true** — there is no `paid_through`-style field yet (`be_features_tracker.md` Gap 71). Only the `billing_plan` promotion happens.

### Tasks
- [x] **Task 3.1.1: Add Combined Pro card to Pricing Table** — Built 2026-07-31. Third card in `PricingTable.tsx` (₹8,999/month, emerald `border-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.3)]` styling with a "Receiving + Sending" badge to visually distinguish it from the indigo "Most Popular" Pro card). Verified live via an interactive Playwright MCP browser session (screenshot at 1280×900) — not a committed test, see Verification Plan below.
- [x] **Task 3.1.2: Support Upgrade Checkout** — Built 2026-07-31. The Combined Pro card's button calls the same `handleSelectPlan('pro_combined')` → `create_checkout_session(plan='pro_combined')` path as any other plan selection — no separate upgrade-specific endpoint needed, matching the spec's reasoning. **Known cosmetic gap, not functional**: the pricing page doesn't yet know or display the signed-in user's *current* plan, so an existing `pro` tenant sees the same "Start Combined Pro Trial" wording a new visitor would, rather than "Upgrade to Combined" — the checkout itself works correctly either way (it's the same call, same result), this is purely a copy/UX polish item for later, not blocking.
- [x] **Task 3.1.3: Confirm Plan Promotion on Success** — Already satisfied by `payu_success()` (built 2026-07-31, see `feature_11_billing.md`) — it promotes `billing_plan` to whatever plan the checkout was created for, no plan-specific branching needed. **Completed 2026-08-02**: the *confirmation the user sees* now exists too — `app/billing/success/page.tsx` renders the Combined Pro name/price from `?plan=pro_combined`. Before this, the promotion happened correctly in the database but the user was redirected to a non-existent route and saw a 404.

### Verification Plan
* **Manual Verification**:
  * Card rendering, styling, and signed-out redirect behavior verified live via an interactive Playwright MCP browser session (2026-07-31) — **not a committed test suite**: `apps/invoice-website` has no Playwright config/spec files/dependency, this was a one-off interactive check.
  * **Not yet done**: an actual upgrade checkout run by a signed-in `pro` tenant through to a verified `pro_combined` promotion — needs a real Clerk-authenticated session with an existing paid plan to test, which wasn't available in this pass. Cycle-start-date reset also depends on the `paid_through`-style field proposed in the new `be_features_tracker.md` Gap 71 — that field doesn't exist yet, so "resets the cycle start date" isn't literally true today; `billing_plan` promotion itself is confirmed working.
