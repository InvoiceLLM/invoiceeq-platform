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
* Navigation Header: `apps/invoice-website/components/marketing/Header.tsx`
* Hero & Live Demo Console: `apps/invoice-website/components/marketing/Hero.tsx`
* Benefits Strip: `apps/invoice-website/components/marketing/BenefitsStrip.tsx`
* Cursor Spotlight Effect: `apps/invoice-website/components/marketing/MouseSpotlight.tsx`
* Site Footer: `apps/invoice-website/components/marketing/Footer.tsx`

### Tasks
- [x] **Task 1.1: Configure Global Tailwind CSS stylesheet**
  - Match theme variables inside `globals.css` with dashboard variables to maintain complete design system consistency.
- [x] **Task 1.2: Build Landing Navigation Header** — re-documented 2026-07-28 with the actual implementation detail (original text described only static nav links; the real component is more interactive); nav-link list corrected 2026-07-29 after `#pricing`/`#how-it-works` dead links (no matching sections ever existed on the page) were removed from `Header.tsx`.
  - `Header({ onOpenFlowsModal })` in `components/marketing/Header.tsx`: a sticky header that darkens (`scrolled` state, toggled on a `window.scroll` listener past 20px) as the page scrolls.
  - Nav links: **Architecture Flow** (styled with a "Live" badge — calls `onOpenFlowsModal()` if provided, else falls through to its `#architecture-flows` anchor href), **Features** (`#features` anchor, matches `WorkspaceShowcase.tsx`'s `id="features"`), **Login** (`/login`).
  - `Get Started Free` CTA button → `/login`.
  - Mobile: hamburger toggle (`mobileMenuOpen` state) opens a full-width drawer with the same links (Features, Login) plus the CTA button, each closing the drawer on click.
- [x] **Task 1.3: Code Hero Text & Call-To-Action** — re-documented 2026-07-28; the actual `Hero.tsx` is a substantially larger interactive component than the original text implied (title/subtitle/two buttons) — it's a full simulated live-demo console, not just static hero copy.
  - `Hero({ onOpenFlowsModal })` in `components/marketing/Hero.tsx`. Heading: *"Automated Invoice Intelligence"*; subheading: *"Extract, verify and understand every invoice using intelligent AI agents — inside your own secure enterprise workspace."*
  - **4 animated agent capability pills** (NOVA/SENTINEL/SAGE/EVOLVE, `HERO_CAPABILITIES` array) below the heading, auto-cycling a highlighted state every 1.5s (`highlightedPillIndex` state + `setInterval`), each with a hover tooltip describing what that agent does; clicking a pill manually re-targets the highlight.
  - **3 CTA buttons**: `Start Free Trial` (`/login`), `Simulate Pipeline` (scrolls to `#pipeline-demo`), `Architecture Flow` (calls `onOpenFlowsModal()`, falling back to scrolling to `#architecture-flows`).
  - **Interactive pipeline demo console** (`#pipeline-demo`): a 3D-tilting card (`cardRef`, mouse-move handler `handleMouseMove`/`handleMouseLeave` computing `rotateX`/`rotateY`, plus a separate scroll-driven parallax tilt/scale effect) containing:
    - A sample-invoice switcher (3 hardcoded samples in `SAMPLE_INVOICES`: `INV-9842`/TechCorp, `FRT-1048`/Global Freight Logistics, `SUB-7721`/Azure Cloud Enterprise Services) — clicking one calls `runLiveSimulation(invoice)`, which resets and animates through a 4-stage progression every 600ms: *Secure Upload → NOVA Extraction → SENTINEL Review → Verified Result* (`activeStep` state, `0`-`3`).
    - An "Inspector" panel with two tabs (`inspectorTab` state): **Line Items Breakdown** (renders `selectedInvoice.taxBreakdown` rows) and **Agent JSON Consensus** (renders `selectedInvoice.rawJson`, a pretty-printed mock extraction result).
    - A "Re-Run Extraction Test" button that re-triggers `runLiveSimulation` on the currently selected invoice.
- [x] **Task 1.4: Build Benefits Strip** — backfilled 2026-07-28, found already built and undocumented.
  - `BenefitsStrip()` renders a row of benefit callouts (title/icon/accent color per item — e.g. "Less Manual Data Entry" with a `Zap` icon) below the hero section.
- [x] **Task 1.5: Add Cursor Spotlight Effect** — backfilled 2026-07-28, found already built and undocumented.
  - `MouseSpotlight()` (`"use client"`) tracks cursor position via a `mousemove` listener and renders a following glow effect. Wired once into `app/layout.tsx`, so it applies site-wide across every page, not just the landing page.
- [x] **Task 1.6: Build Site Footer** — backfilled 2026-07-28, found already built and undocumented.
  - `Footer()` renders the shared site footer (brand mark, nav links) via `lucide-react` icons (`FileText`, `Shield`, `Lock`, `ExternalLink`); mounted once in `app/layout.tsx` beneath `{children}`, so it appears on every page.

### Verification Plan
* **Manual Verification**: Run Next.js marketing site (`npm run dev` in `apps/invoice-website`) and check browser page loading, responsive menu wraps, and styling details.
