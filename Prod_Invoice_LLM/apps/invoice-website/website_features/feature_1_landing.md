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
  - Nav links: **Architecture Flow** (styled with a "Live" badge — calls `onOpenFlowsModal()` if provided, else falls through to its `#architecture-flows` anchor href), **Features** (`#features` anchor, matches `WorkspaceShowcase.tsx`'s `id="features"`), **Pricing** (`#pricing`), **Login** (`/login`).
  - **Logotype** (updated 2026-08-05, Gap 163): the wordmark is "Invoice" in the system serif stack (`ui-serif, Georgia, Cambria, "Times New Roman", Times, serif`) at `text-2xl`, followed by "AI" in a small cyan-bordered monospace tag (`border-[#22D3EE]/40 bg-[#22D3EE]/10`), replacing the previous single-weight sans `Invoice.AI`. Both react to the shared `group-hover` glow. Note: the Gap 163 mockup showed this logotype inside the hero viewport, but the real wordmark lives in `Header.tsx` (`Hero.tsx` never had one), so the refinement was applied here rather than duplicating a second wordmark into the hero.
  - **Route-based active-page indicator** (added 2026-08-05, Gap 159): `isActive(href)` compares `usePathname()` against each link's href — path links match on `pathname === href || pathname.startsWith(href + "/")`; same-page section links (`#features`/`#pricing`/`#architecture-flows`) additionally require `pathname === "/"` **and** a matching `window.location.hash`, tracked in a `hash` state seeded on mount, refreshed on `hashchange`, and set directly in each hash link's `onClick` (Next's client-side `Link` navigation uses `pushState`, which does not fire `hashchange`). The result is that exactly one nav item can be active at a time. Active links get `NAV_ACTIVE` (`text-white` + blue drop-shadow glow) plus `aria-current="page"`; the rest get `NAV_IDLE` (hover-only glow). This replaced the previous hardcoded cyan highlight on Architecture Flow, which was a fixed style rather than a computed state — that link keeps its cyan "Live" badge, which is a separate signifier, not the active indicator.
  - `Get Started Free` CTA button → `/login`.
  - Mobile: hamburger toggle (`mobileMenuOpen` state) opens a full-width drawer with the same links (Features, Pricing, Login) plus the CTA button, each closing the drawer on click. Drawer links use `drawerLinkClass(href)`, the same `isActive` computation rendered as a filled `bg-white/10` row instead of a glow.
- [x] **Task 1.3: Code Hero Text & Call-To-Action** — re-documented 2026-07-28; the actual `Hero.tsx` is a substantially larger interactive component than the original text implied (title/subtitle/two buttons) — it's a full simulated live-demo console, not just static hero copy. **Above-the-fold block rebuilt 2026-08-05 (Gap 163)**; the pipeline demo console below it was deliberately left untouched.
  - `Hero()` in `components/marketing/Hero.tsx`. The `onOpenFlowsModal` prop was **removed** in the Gap 163 rebuild — the only thing that used it was the hero's "Architecture Flow" button, which is gone; `app/page.tsx` now renders `<Hero />` and the Architecture Flow modal keeps its two remaining entry points (the header nav item and `FlowsShowcaseSection`).
  - **Headline**: *"Invoices, understood automatically"* (was *"Automated Invoice Intelligence"*, which wrapped to two lines). Rendered through the existing `.animated-hero-heading` class, whose font stack was widened to `ui-serif, Georgia, Cambria, "Times New Roman", Times, serif` (system fonts only — no download, no CDN/CSP exposure). Sized `text-3xl sm:text-5xl xl:text-6xl` with `lg:whitespace-nowrap`: the step up to `text-6xl` is held at `xl`, not `lg`, because at 60px the string measures ~1038px and would overflow the container at exactly the 1024px `lg` breakpoint. Measured one line at 1024/1280/1536/1920 with no horizontal overflow.
  - **Subheading** cut to one short line: *"From inbox to verified data — no manual keying."*
  - **CTA row reduced from 3 buttons to 1** — `Start Free Trial` (`/login`) plus a quiet, non-button "See how it flows" scroll cue with a bouncing `ChevronDown` anchored to `#pipeline-demo`. `Simulate Pipeline` and `Architecture Flow` were removed: the pipeline demo sits directly below this block and Architecture Flow is a header nav item, so both already had a home.
  - **Flow-diagram centrepiece** replacing the old 4-card capability grid: `FlowNode` (a local presentational component — icon tile, title, caption, accent colour) renders two input nodes (**Email Inbox**, **Drive & Salesforce**) on the left and two output nodes (**Verified Data**, **Webhooks**) on the right, flanking a glowing 104px "AI ENGINE" ring (blurred `#3B82F6` halo + a slowly rotating dashed 132px ring). The four agents are now a compact colour-keyed legend under the ring (`AGENT_LEGEND`: NOVA/Extracts cyan, SENTINEL/Verifies emerald, SAGE/Answers violet, EVOLVE/Learns indigo) rather than four standalone cards; the pre-existing 1.5s `highlightedPillIndex` interval now drives which legend entry is lit instead of which card is raised. Two `.flowing-beam` connectors are absolutely positioned against the ring (`top-[52px]`, `right-[calc(50%_+_52px)]`/`left-[calc(50%_+_52px)]`) so they always terminate on the circle's edge regardless of how wide the legend renders; they're `hidden` below `lg`, where the whole diagram stacks vertically.
  - **Sample-invoice result card** below the diagram — same `SAMPLE_INVOICES` data the pipeline demo runs on, bound to the shared `selectedInvoice` state, showing vendor, invoice/PO number, extracted total, field precision and status badge, so the diagram lands on a concrete outcome.
  - **Trust-signal row** closes the above-the-fold block: VNet-isolated tenant / AES-256 encrypted storage / No card required to start. Verified at 1440×700 that the entire block from nav through this row ends at y≈640, i.e. inside a real ~700px viewport with no scrolling.
  - **Explicitly rejected during design**: a robot/mascot icon for the AI Engine core — kept as an abstract ring plus legend instead.
  - **Interactive pipeline demo console** (`#pipeline-demo`, unchanged by Gap 163): a 3D-tilting card (`cardRef`, mouse-move handler `handleMouseMove`/`handleMouseLeave` computing `rotateX`/`rotateY`, plus a separate scroll-driven parallax tilt/scale effect) containing:
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
