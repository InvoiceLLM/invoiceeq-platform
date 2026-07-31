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
- [x] **Task 3.1: Build Pricing Cards Layout** — Built 2026-07-31. `components/marketing/PricingTable.tsx` — 3 cards (Free/Pro/Pro Combined, see Feature 3.1 below for the third), matching the spec's border/badge styling exactly (Free: `border-[#222D3D] hover:border-slate-700`; Pro: `border-indigo-600 shadow-[0_0_20px_rgba(99,102,241,0.3)]` + `bg-indigo-600` "Most Popular" badge). Wired into `app/page.tsx` between `WorkspaceShowcase` and `BenefitsStrip`; added a "Pricing" nav link (`#pricing` anchor) to `Header.tsx`, desktop + mobile.
- [x] **Task 3.2: Connect PayU Checkout Form** — Built 2026-07-31. New proxy route `app/api/billing/create-checkout-session/route.ts` (same shape as the existing `/api/auth/provision` proxy) — requires a real signed-in Clerk session (`auth()`), forwards the caller's token to the backend so `routers/billing.py`'s Admin-role gate can verify it, then relays the hash-signed field set back to the browser. `PricingTable.tsx` builds a hidden form from those fields and submits it — confirmed via Playwright that a signed-out click correctly redirects to `/signup?plan=pro`/`/signup?plan=pro_combined` first (checkout requires an authenticated Admin tenant context, so an anonymous visitor has to create an account before paying — same pattern as this site's existing "Get Started Free" CTA).
- [x] **Task 3.3: Implement PayU Success/Failure Result Pages** — Already built as part of `routers/billing.py` (`payu_success()`/`payu_failure()`, 2026-07-31 — see `feature_11_billing.md`). No additional website-side work needed; PayU never lands on `invoice-website` directly.
- [x] **Task 3.4: Implement past-due lockouts** — Already built (`dependencies.py`'s `402` block, pre-existing). **Caveat found while finishing this feature: see new Gap 71 in `be_features_tracker.md`** — the block is real but nothing currently ever sets `billing_plan = "unpaid"`, so it's presently unreachable in practice. Tracked separately, not blocking this feature's completion.

### Verification Plan
* **Automated Tests**: Mock PayU response hashes and `verify_payment` responses in `pytest`, verifying that only a fully-verified success updates `billing_plan`, and that a lapsed renewal locks the tenant. **Not yet built.**
* **Manual Verification**: 
  * Visual + signed-out click flow verified live via Playwright screenshot + navigation assertion (2026-07-31) — pricing cards render correctly at 1280×900, "Start Pro Trial"/"Start Combined Pro Trial" correctly redirect to `/signup?plan=...` when signed out.
  * **Not yet done**: an actual signed-in checkout run all the way to PayU's hosted page and back through `payu_success()` — needs a real Clerk-authenticated Admin session, which the automated Playwright pass didn't have. `tsc --noEmit` clean throughout.
