# Feature Website 1: Landing Page & Core Shell

Configure the visual entry point, shared design system styling, header navigation structure, and hero page actions.

### Theme & Styling Specifications
* Canvas background color: `#0B0F19`
* Main Panel borders: `#222D3D`
* Headings: Gradient text from purple/blue to green/teal (`bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-sky-400 to-emerald-400`).
* Buttons: Primary actions styled in vibrant emerald green (`bg-[#10B981] hover:bg-[#059669] text-white`). Secondary buttons styled in transparent ghost borders (`border border-[#222D3D] hover:bg-slate-900`).

### File Coordinates
* Main Page: `apps/invoice-website/app/page.tsx`
* Layout Settings: `apps/invoice-website/app/layout.tsx`
* Stylesheet: `apps/invoice-website/app/globals.css`
* Benefits Strip: `apps/invoice-website/components/marketing/BenefitsStrip.tsx`
* Cursor Spotlight Effect: `apps/invoice-website/components/marketing/MouseSpotlight.tsx`
* Site Footer: `apps/invoice-website/components/marketing/Footer.tsx`

### Tasks
- [x] **Task 1.1: Configure Global Tailwind CSS stylesheet**
  - Match theme variables inside `globals.css` with dashboard variables to maintain complete design system consistency.
- [x] **Task 1.2: Build Landing Navigation Header**
  - Code headers linking to: Features, Pricing, How It Works, and Login.
  - Implement a `Get Started Free` button routing directly to SSO signup page.
- [x] **Task 1.3: Code Hero Text & Call-To-Action**
  - Implement the title: *"AI-Powered Invoice Processing — Built for Every Business"*.
  - Add descriptions: *"Your own private, secure workspace. Your invoices, your team, your rules."*
  - Build `Start Free` and `Book a Demo` landing action buttons.
- [x] **Task 1.4: Build Benefits Strip** — backfilled 2026-07-28, found already built and undocumented.
  - `BenefitsStrip()` renders a row of benefit callouts (title/icon/accent color per item — e.g. "Less Manual Data Entry" with a `Zap` icon) below the hero section.
- [x] **Task 1.5: Add Cursor Spotlight Effect** — backfilled 2026-07-28, found already built and undocumented.
  - `MouseSpotlight()` (`"use client"`) tracks cursor position via a `mousemove` listener and renders a following glow effect. Wired once into `app/layout.tsx`, so it applies site-wide across every page, not just the landing page.
- [x] **Task 1.6: Build Site Footer** — backfilled 2026-07-28, found already built and undocumented.
  - `Footer()` renders the shared site footer (brand mark, nav links) via `lucide-react` icons (`FileText`, `Shield`, `Lock`, `ExternalLink`); mounted once in `app/layout.tsx` beneath `{children}`, so it appears on every page.

### Verification Plan
* **Manual Verification**: Run Next.js marketing site (`npm run dev` in `apps/invoice-website`) and check browser page loading, responsive menu wraps, and styling details.
