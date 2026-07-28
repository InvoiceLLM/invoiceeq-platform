# Website Features Progress Tracker

This document tracks the implementation progress of the marketing website, SSO provisioning, and subscription billing pages for `invoice-website`.

## Gap Analysis Integration

**Current Status:** 0% complete (all 4 features missing)

**Critical Missing Features:**
- Feature 4: Clerk Auth Gateway & Company Provisioning - CRITICAL for user onboarding
- Feature 1: Landing Page & Core Shell - Public entry point
- Feature 3: Pricing Table & Stripe Integration - Required for monetization
- Feature 2: Multi-Tenant Workspace Showcase - Marketing feature

---

## Feature Tracker

- `[ ]` [Feature 1: Landing Page & Core Shell](feature_1_landing.md)
- `[ ]` [Feature 2: Multi-Tenant Workspace Showcase](feature_2_showcase.md)
- `[ ]` [Feature 3: Pricing Table & Stripe Checkout Integration](feature_3_pricing_stripe.md)
- `[ ]` [Feature 4: Clerk Auth Gateway & Company Provisioning](feature_4_auth_gateway.md)
- [ ] [Feature 3.1: Service Flow Pricing Tier](feature_3.1_vendor_flow_pricing.md) — **DECIDED** (Combined Pro at ₹8,999/month), upgrading and proration flows mapped.

## Open Items / Gaps

- `[ ]` **Gap 1: "See it in action" CTA linking to the flows visualizer** — flagged 2026-07-27, not implemented (deliberately — Feature 1 is still unbuilt, don't want to guess at a design someone else may already be mid-build on). When [Feature 1: Landing Page & Core Shell](feature_1_landing.md) gets built, add a CTA button/section linking to `invoice-fe`'s `/flows` page (`apps/invoice-fe/app/flows/page.tsx` — see `apps/invoice-fe/docs/feature_11_flows_visualization.md`), a standalone, no-login animated walkthrough of the real system (Inbound pipeline + Chat agent) plus the Service Flow design (Outbound + Direction-Aware Chat, clearly marked spec-only). Confirmed it needs zero auth to work today (no `middleware.ts`/Clerk anywhere in `invoice-fe`) and as of 2026-07-27 no longer shows the authenticated app's Sidebar/Header when visited directly (Gap 62). Implementation note for whoever picks this up: `invoice-website` and `invoice-fe` are separate deployments with no shared routing, so the CTA must be a plain `<a href>` to `invoice-fe`'s `/flows` URL (via an env var for the FE base URL), not an internal Next.js `<Link>`.
