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
│   ├── login/page.tsx           # Clerk sign-in (role toggle + OTP second factor)
│   ├── signup/page.tsx          # Clerk sign-up + org creation + backend provisioning call
│   └── api/webhooks/stripe/    # empty (.gitkeep only) — no Stripe integration exists
├── components/
│   ├── ui/                     # empty (.gitkeep only) — no Shadcn/UI components exist
│   └── marketing/              # Header, Hero, WorkspaceShowcase, AITeamSection, FlowsShowcaseSection, FlowsModal, BenefitsStrip, MouseSpotlight, Footer
├── lib/
│   └── utils.ts                 # Tailwind class merger (no stripe.ts)
└── middleware.ts                 # bare clerkMiddleware() — makes Clerk auth context available; no route protection enforced
```

## Key Pages & Sections
- **Hero Section** — animated NOVA/SENTINEL/SAGE/EVOLVE capability pills + interactive simulated pipeline-demo console + "Start Free Trial" / "Simulate Pipeline" / "Architecture Flow" CTAs
- **Flows Showcase Section** — 4 flow tiles that open a live preview of `invoice-fe`'s `/flows` page in a modal/iframe
- **AI Team Section** — showcases the four branded AI agents (NOVA, SENTINEL, SAGE, EVOLVE)
- **Workspace Showcase** — interactive 3-column tenant isolation widget (Acme Corp, TechFirm, GlobalTrade) plus a "Live Data Isolation Probe Simulator"
- **Benefits Strip** — row of benefit callouts below the hero
- **Auth** — Clerk-based signup (`/signup`) and login (`/login`, with admin/user role toggle + OTP second factor); no pricing page and no Stripe checkout exist yet

## Environment Variables
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
NEXT_PUBLIC_FE_URL=
NEXT_PUBLIC_BACKEND_API_URL=
```
There are no Stripe-related environment variables — no Stripe integration is implemented in this app.
