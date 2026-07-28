# Feature Website 2: Multi-Tenant Workspace Showcase

Implement the interactive multi-tenant workspace showcase widget to visualize data isolation across companies.

### Theme & Styling Specifications
* Card outline gradients:
  * Acme Corp: Green border (`border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.1)]`).
  * TechFirm Ltd: Purple border (`border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.1)]`).
  * GlobalTrade Inc: Gold border (`border-amber-500/30 shadow-[0_0_15px_rgba(245,158,11,0.1)]`).
* Privacy badges: `bg-emerald-950/20 text-emerald-400 border border-emerald-800/40 rounded px-2 py-0.5 text-xs`.

### File Coordinates
* Component: `apps/invoice-website/components/marketing/WorkspaceShowcase.tsx`
* AI Team Section: `apps/invoice-website/components/marketing/AITeamSection.tsx`
* Flows Showcase Section: `apps/invoice-website/components/marketing/FlowsShowcaseSection.tsx`
* Flows Modal: `apps/invoice-website/components/marketing/FlowsModal.tsx`

### Tasks
- [x] **Task 2.1: Implement Workspace Showcase Container Layout**
  - Create the layout section: *"Every Company Gets Their Own Private Workspace"*.
  - Add text detailing: *"Your data never mixes with another company. Think of it as your own private office — just on the cloud."*
- [x] **Task 2.2: Render Interactive Tenant Profile Cards**
  - Render three mock cards side-by-side representing Acme Corp, TechFirm, and GlobalTrade.
  - Display simulated user lists with specific roles: `Admin`, `Auditor`, `Loader`.
  - Embed dynamic metrics counters for each (e.g. `1,240 invoices processed`).
- [x] **Task 2.3: Build Privacy Seal Banner**
  - Place a bottom notification banner: `🔒 Data between companies is completely sealed — no crossover, ever.` styled in a dark teal glassmorphic border.
- [x] **Task 2.4: Build AI Team Section** — backfilled 2026-07-28, found already built and undocumented.
  - `AITeamSection()` showcases the four branded AI agents this platform is built around: **NOVA** (Smart Invoice Extraction), **SENTINEL** (Invoice Risk Detection), **SAGE** (Invoice Intelligence Chat), **EVOLVE** (Continuous Learning).
- [x] **Task 2.5: Build Flows Showcase Section** — backfilled 2026-07-28, found already built and undocumented. Also closes Gap 1 below (the "See it in action" CTA).
  - `FlowsShowcaseSection({ onOpenModal })` renders the 4 featured-flow tiles (Inbound, Outbound/Vendor, Chat, Direction-Aware) plus a "Launch Live Simulator" button (opens `FlowsModal`) and a "Full Tab" external link, both ultimately pointing at `invoice-fe`'s `/flows` page via `${NEXT_PUBLIC_FE_URL}/flows`.
- [x] **Task 2.6: Build Flows Modal** — backfilled 2026-07-28, found already built and undocumented.
  - `FlowsModal({ isOpen, onClose, initialFlowId })` embeds `invoice-fe`'s `/flows` page live in an iframe (`src={flowsUrl}`) for in-page preview, deep-linking to a specific flow tab via `?flow=<id>` (matches the `useEffect` reading `flow`/`tab`/`type` URL params added to `invoice-fe/app/flows/page.tsx`), plus an "Open Full Screen" external link using the same URL.

### Verification Plan
* **Manual Verification**: Verify spacing and rendering across mobile viewports, ensuring grid wraps gracefully.
