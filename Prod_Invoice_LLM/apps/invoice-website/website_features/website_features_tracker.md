# Website Features Progress Tracker

This document tracks the implementation progress of the marketing website, SSO provisioning, and subscription billing pages for `invoice-website`.

## Gap Analysis Integration

**Current Status:** 75% complete (3 of 4 features complete)

**Completed Features:**
- Feature 1: Landing Page & Core Shell — Public entry point & design tokens
- Feature 2: Multi-Tenant Workspace Showcase — Interactive tenant isolation showcase
- Feature 4: Clerk Auth Gateway & Company Provisioning — Signup/login/org provisioning built (see Gap 2 below for what's still needed before it's production-usable)

**Critical Missing Features:**
- Feature 3: Pricing Table & Stripe Integration - Required for monetization

---

## Feature Tracker

- `[x]` [Feature 1: Landing Page & Core Shell](feature_1_landing.md)
- `[x]` [Feature 2: Multi-Tenant Workspace Showcase](feature_2_showcase.md) — includes **AITeamSection** showcasing the four AI agents: **NOVA** (Smart Invoice Extraction), **SENTINEL** (Invoice Risk Detection), **SAGE** (Invoice Intelligence Chat), **EVOLVE** (Continuous Learning)
- `[ ]` [Feature 3: Pricing Table & Stripe Checkout Integration](feature_3_pricing_stripe.md)
- `[x]` [Feature 4: Clerk Auth Gateway & Company Provisioning](feature_4_auth_gateway.md) — reconciled from the `auth-feature-4` branch onto current master (2026-07-28); see Gap 2/3 below
- [ ] [Feature 3.1: Service Flow Pricing Tier](feature_3.1_vendor_flow_pricing.md) — **DECIDED** (Combined Pro at ₹8,999/month), upgrading and proration flows mapped.

## Open Items / Gaps

- `[ ]` **Gap 1: "See it in action" CTA linking to the flows visualizer** — flagged 2026-07-27, not implemented (deliberately — Feature 1 is still unbuilt, don't want to guess at a design someone else may already be mid-build on). When [Feature 1: Landing Page & Core Shell](feature_1_landing.md) gets built, add a CTA button/section linking to `invoice-fe`'s `/flows` page (`apps/invoice-fe/app/flows/page.tsx` — see `apps/invoice-fe/docs/feature_11_flows_visualization.md`), a standalone, no-login animated walkthrough of the real system (Inbound pipeline + Chat agent) plus the Service Flow design (Outbound + Direction-Aware Chat, clearly marked spec-only). Confirmed it needs zero auth to work today (no `middleware.ts`/Clerk anywhere in `invoice-fe`) and as of 2026-07-27 no longer shows the authenticated app's Sidebar/Header when visited directly (Gap 62). Implementation note for whoever picks this up: `invoice-website` and `invoice-fe` are separate deployments with no shared routing, so the CTA must be a plain `<a href>` to `invoice-fe`'s `/flows` URL (via an env var for the FE base URL), not an internal Next.js `<Link>`.
  - **Update 2026-07-28:** Feature 4's `FlowsShowcaseSection.tsx`/`FlowsModal.tsx` (built alongside Feature 1/2) actually already implement this CTA — a "Full Tab" link and an embedded iframe modal, both pointing at `${NEXT_PUBLIC_FE_URL}/flows`, with per-flow deep-linking via `?flow=<id>`. This gap can be marked resolved; tracker checkbox above wasn't updated when that landed.
- `[ ]` **Gap 2: Real Clerk API keys needed** — flagged 2026-07-28. Feature 4 (`invoice-fe` and `invoice-website` both) currently runs on placeholder Clerk keys (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`/`CLERK_SECRET_KEY` in each app's `.env.local`) that are only format-valid, not real — they let `clerkMiddleware()`/`ClerkProvider` initialize without crashing (structurally verified: homepage, `/login`, `/signup` all render correctly), but any real Clerk API call (actual signup, actual sign-in, JWKS verification) will fail until real keys from the Clerk Dashboard replace them. Needed in 3 places: `invoice-be/.env` already has a real `CLERK_SECRET_KEY` for JWT verification, but no `invoice-fe`/`invoice-website` publishable key has ever existed in this repo. See `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` §1 for the Clerk Dashboard setup steps.
- `[ ]` **Gap 3: `/forgot-password` link is a dead route** — flagged 2026-07-28. `invoice-website/app/login/page.tsx`'s login form links to `/forgot-password`, carried over from the `auth-feature-4` branch's original design; that route was never built (pre-existing gap in the source branch, not introduced by the reconciliation). Not blocking for Feature 4's core signup/login flow.
- **Decision (2026-07-28):** Whether `/` shows the marketing homepage or redirects straight to login was an open architectural question raised during Feature 4 reconciliation (the `auth-feature-4` branch's `pages/index.jsx` redirected `/` straight to `/admin/login`, replacing the whole marketing site). Resolved: homepage stays the Feature 1 marketing landing page; login/signup live at their own `/login`/`/signup` routes.

---

## Gap Items (Future)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Privacy Policy Page | `[ ]` Pending | Required for legal compliance before production launch |
| 2 | Terms & Conditions Page | `[ ]` Pending | Required for legal compliance before production launch |
