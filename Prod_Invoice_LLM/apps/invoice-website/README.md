# Invoice AI — Marketing Website (`/apps/invoice-website`)

## Purpose
Public-facing marketing site for the Invoice AI platform. Handles visitor-facing marketing content and Clerk-based sign-up/login/org provisioning. There is no payments/billing functionality yet (see `website_features/feature_3_pricing_payu.md` — planned, not built).

## Tech Stack
| Layer          | Technology                        |
|----------------|-----------------------------------|
| Framework      | Next.js 14.2 (App Router)         |
| Language       | TypeScript                        |
| Styling        | Tailwind CSS                      |
| Auth           | Clerk (`@clerk/nextjs`)           |

## Directory Structure
```
invoice-website/
├── app/
│   ├── layout.tsx              # Root layout: ClerkProvider, MouseSpotlight, global background, Footer
│   ├── page.tsx                # Landing page: Header, Hero, FlowsShowcaseSection, AITeamSection, WorkspaceShowcase, BenefitsStrip, FlowsModal
│   ├── login/page.tsx          # Clerk sign-in (role toggle + OTP second factor) + forgot password link (Gap 3)
│   ├── signup/page.tsx         # Clerk sign-up + org creation + server-side provision call (Gap 7)
│   ├── forgot-password/page.tsx # Two-step password reset using Clerk reset_password_email_code (Gap 3)
│   ├── billing/success/page.tsx # PayU return page — upgrade confirmed (public, no Clerk gate, no API call)
│   ├── billing/failed/page.tsx  # PayU return page — maps the backend's reason codes to 3 severities (public)
│   ├── contact/page.tsx         # Contact Us form — category, urgency pills, message, hidden honeypot (Feature 5 / Gap 183)
│   ├── api/
│   │   ├── auth/provision/route.ts             # Server-side proxy for backend /auth/provision (Gap 7)
│   │   ├── contact/route.ts                    # Server-side proxy → BE POST /api/v1/support/contact
│   │   │                                       # (public/unauthenticated; honeypot + IP rate limit, BE Gap 249)
│   │   ├── billing/create-checkout-session/route.ts  # Clerk-gated proxy that starts a PayU checkout
│   │   └── v1/billing/payu/{success,failure}/route.ts # PayU surl/furl pass-through (UNauthenticated by design) + shared relay.ts
│   │   └── v1/email/mailintegration/route.ts          # SendGrid Inbound Parse pass-through → BE (Gap 124 public URL; UNauthenticated)
├── components/
│   ├── ui/                     # empty (.gitkeep only) — no Shadcn/UI components exist
│   └── marketing/              # Header, Hero, WorkspaceShowcase, AITeamSection, FlowsShowcaseSection, PricingTable, FlowsModal, BenefitsStrip, MouseSpotlight, Footer,
│                               # HeroModeTabs, SageChatPreview, WorkflowRecipeSelector (Feature 7 — all fixture-driven, zero network calls)
├── lib/
│   ├── utils.ts                # Tailwind class merger
│   └── billingPlans.ts         # Plan copy + searchParams/app-link helpers for the two /billing pages
├── middleware.ts               # bare clerkMiddleware() — makes Clerk auth context available; no route protection enforced
└── website_features/           # Implementation documentation for Gaps 3 & 7
```

## Key Pages & Sections
- **Hero Section** — animated NOVA/SENTINEL/SAGE/EVOLVE capability pills + interactive simulated pipeline-demo console + "Start Free Trial" / "Simulate Pipeline" / "Architecture Flow" CTAs
- **Flows Showcase Section** — 4 flow tiles that open a live preview of `invoice-fe`'s `/flows` page in a modal/iframe
- **AI Team Section** — showcases the four branded AI agents (NOVA, SENTINEL, SAGE, EVOLVE)
- **Workspace Showcase** — interactive 3-column tenant isolation widget (Acme Corp, TechFirm, GlobalTrade) plus a "Live Data Isolation Probe Simulator"
- **Plug & Play marketing surface (Feature 7, Gaps 345–348)** — three new homepage pieces, **all fixture-driven with zero network calls** (a hard constraint, not a shortcut: `/` is public and unauthenticated, so a live SAGE call here would be an open, uncapped LLM endpoint for anonymous traffic — see `website_features/feature_7_plug_and_play_workflows.md` §7):
  - `HeroModeTabs` — a "Complete Web Application" / "Plug & Play Engine" switcher in the hero. The plug panel shows the 4 primitives (email in, Drive sync, REST API, webhooks) as capability tiles.
  - `SageChatPreview` (`#sage-preview`) — 3 pre-seeded prompt chips; clicking one reveals a canned answer, the SQL it resolved to, and invoice citation pills, all from a local constant.
  - `WorkflowRecipeSelector` (`#choose-your-workflow`) — 4-step selector (Input Channel → Audit Level → Output Destination → Chat Access) driving a live summary line. Its CTA points at `/signup`, **not** a sandbox-key endpoint — BE Gap 340 has not shipped; a code comment marks the retarget.
  - `Hero`'s pipeline demo also gained a real SENTINEL discrepancy sample (`FRT-1048`, `AUDIT_REQUIRED`, held for review) — before this, `SampleInvoice.status` had no alert variant and all three samples auto-approved.
  - **No Playwright coverage** for any of the above; verified by typecheck, `next build` and a scripted headless-Chrome run only.
- **Benefits Strip** — row of benefit callouts below the hero
- **Auth** — Clerk-based signup (`/signup`) and login (`/login`, with admin/user role toggle + OTP second factor)
- **Password Reset** — Two-step forgot password flow (`/forgot-password`) using Clerk's `reset_password_email_code` strategy (Gap 3)
- **Pricing & PayU checkout** — `PricingTable` (Free / Pro / Pro Combined) on the landing page at `#pricing`, submitting a hash-signed hidden form to PayU's hosted page. *(This bullet previously read "No pricing page — no PayU checkout exists yet"; that was stale from 2026-07-31.)*
- **PayU return pages** — `/billing/success` and `/billing/failed`, both **public and deliberately not Clerk-gated** (a user coming back from PayU may have no session in that tab). `/billing/failed` distinguishes an honest decline (retry offered) from "we could not verify" and from "you were charged but we couldn't apply it" (no retry offered — see `website_features/feature_3_pricing_payu.md`).
- **PayU callback pass-through** — `/api/v1/billing/payu/{success,failure}`, path-identical to the backend's own endpoints. Unauthenticated on purpose: PayU carries no session, and the backend independently verifies the response hash plus a server-to-server `verify_payment` before trusting anything. `invoice-be`'s ingress is internal-only, so without this route PayU could not deliver the callback at all.
- **Contact Us** — `/contact` (Feature 5, Gap 183), linked from `Header.tsx` (desktop nav + mobile drawer) and `Footer.tsx`. Full-page dark glassmorphic form: name, work email, inquiry category (Sales / Technical Support / Billing / Partnership / General), optional company, urgency pills (Low / Normal / Urgent with SLA labels), message with a live 5000-char counter. On success it shows the backend's reference number (`INQ-YYYY-XXXXXXXX`). **Not covered by any Playwright spec** — Task 5.4 of `website_features/feature_5_contact_us.md` was never written, and no live submission through to a real `Application@infinevocloud.com` delivery has been run.
- **Contact proxy** — `/api/contact` → BE `POST /api/v1/support/contact`. Public and unauthenticated by design (same topology as the PayU/SendGrid routes: `invoice-be` ingress is internal-only, so the browser can never reach it directly). Layers a hidden honeypot field (`hp_field` → silent 201, nothing persisted, logged as a WARN so false positives are visible) and a per-instance sliding-window rate limit (5 req / 10 min per resolved client IP, 429 + `Retry-After`) on top of the backend's own Redis-backed limiter, and forwards the resolved IP as `X-Client-IP` — the backend cannot derive it itself, since on that hop the platform-appended XFF entry is this container's pod IP. See BE Gap 249; the proxy layer is best-effort edge shedding only (this app scales 0–3 with scale-to-zero, so a cold start wipes its window).
- **SendGrid Inbound Parse pass-through** — `/api/v1/email/mailintegration`, path-identical to BE. Same topology as PayU: public website → internal BE. Unauthenticated (SendGrid has no session). Live MX/Parse Destination still Gap 124 (`be_features_tracker.md`).

## Recent Changes (auth-feature-4)
- **Gap 3:** Added `/forgot-password` page with two-step Clerk password reset flow
- **Gap 7:** Moved `/auth/provision` call from client-side to server-side proxy (`/api/auth/provision`) — backend URL no longer exposed in browser bundle

## Environment Variables

Required variables (copy `.env.local.example` to `.env.local` and fill in):

```env
# Clerk authentication (publishable key is safe to commit, already in .env.local.example)
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...  # Ask team lead for shared test key

# Cross-app URLs (optional, defaults to these values)
NEXT_PUBLIC_FE_URL=http://localhost:3001
BACKEND_API_URL=http://localhost:8000  # Server-side only (Gap 7)
```

**Note:** `BACKEND_API_URL` is server-side only (no `NEXT_PUBLIC_` prefix) — used by the `/api/auth/provision` route handler. The backend URL never ships to the browser (Gap 7 fix).

There are no PayU-related environment variables — no PayU integration is implemented in this app (billing lives entirely in `invoice-be`, see its README/`feature_11_billing.md`).
