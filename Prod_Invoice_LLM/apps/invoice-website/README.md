# Invoice AI — Marketing Website (`/apps/invoice-website`)

## Purpose
Public-facing marketing site for the Invoice AI SaaS platform.  
Handles visitor conversion, pricing display, SSO authentication, and Stripe payment integration.

## Tech Stack
| Layer          | Technology                        |
|----------------|-----------------------------------|
| Framework      | Next.js (App Router, SSR enabled) |
| Language       | TypeScript                        |
| Styling        | Tailwind CSS                      |
| UI Components  | Shadcn/UI                         |
| Payment        | Stripe Checkout                   |
| Auth           | Clerk / Auth0 (SSO)              |

## Directory Structure
```
invoice-website/
├── app/
│   ├── layout.tsx              # Root Layout (Fonts, Providers, Navbar, Footer)
│   ├── page.tsx                # Landing Page (Hero, Features, Pricing)
│   ├── login/page.tsx          # SSO / Clerk Auth Entry Point
│   └── api/webhooks/
│       └── stripe/route.ts     # Stripe webhook handler
├── components/
│   ├── ui/                     # Shadcn/UI components
│   └── marketing/              # HeroSection, FeatureTeaser, PricingTable
├── lib/
│   ├── stripe.ts               # Stripe SDK init
│   └── utils.ts                # Tailwind class merger
└── middleware.ts               # Auth guard
```

## Key Pages
- **Hero Section** — Value proposition + "Start Free Trial" CTA
- **Feature Teaser** — 3-column grid (Extraction, Verification, Auditor)
- **Security & Trust** — Azure AI Foundry, VNet, RBAC callouts
- **Pricing Plans** — Free Trial (50 invoices) / Pro ($99/mo) / Enterprise
- **Auth/SSO Gateway** — Google & Microsoft sign-in via Clerk/Auth0

## Environment Variables
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
NEXT_PUBLIC_API_URL=
```
