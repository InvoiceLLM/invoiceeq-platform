# Invoice AI — Marketing Website (`/apps/invoice-website`)

## Purpose
Public-facing marketing site for the Invoice AI platform. Handles visitor-facing marketing content and Clerk-based sign-up/login/org provisioning. There is no payments/billing functionality yet (see `website_features/feature_3_pricing_stripe.md` — planned, not built).

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
│   ├── api/
│   │   └── auth/provision/route.ts  # Server-side proxy for backend /auth/provision (Gap 7)
│   └── webhooks/stripe/        # empty (.gitkeep only) — no Stripe integration exists
├── components/
│   ├── ui/                     # empty (.gitkeep only) — no Shadcn/UI components exist
│   └── marketing/              # Header, Hero, WorkspaceShowcase, AITeamSection, FlowsShowcaseSection, FlowsModal, BenefitsStrip, MouseSpotlight, Footer
├── lib/
│   └── utils.ts                # Tailwind class merger (no stripe.ts)
├── middleware.ts               # bare clerkMiddleware() — makes Clerk auth context available; no route protection enforced
└── website_features/           # Implementation documentation for Gaps 3 & 7
```

## Key Pages & Sections
- **Hero Section** — animated NOVA/SENTINEL/SAGE/EVOLVE capability pills + interactive simulated pipeline-demo console + "Start Free Trial" / "Simulate Pipeline" / "Architecture Flow" CTAs
- **Flows Showcase Section** — 4 flow tiles that open a live preview of `invoice-fe`'s `/flows` page in a modal/iframe
- **AI Team Section** — showcases the four branded AI agents (NOVA, SENTINEL, SAGE, EVOLVE)
- **Workspace Showcase** — interactive 3-column tenant isolation widget (Acme Corp, TechFirm, GlobalTrade) plus a "Live Data Isolation Probe Simulator"
- **Benefits Strip** — row of benefit callouts below the hero
- **Auth** — Clerk-based signup (`/signup`) and login (`/login`, with admin/user role toggle + OTP second factor)
- **Password Reset** — Two-step forgot password flow (`/forgot-password`) using Clerk's `reset_password_email_code` strategy (Gap 3)
- **No pricing page** — no Stripe checkout exists yet (see `website_features/feature_3_pricing_stripe.md` — planned, not built)

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

There are no Stripe-related environment variables — no Stripe integration is implemented in this app.
