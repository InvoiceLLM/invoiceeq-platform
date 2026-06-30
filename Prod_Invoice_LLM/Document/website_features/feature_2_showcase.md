# Feature Website 2: Multi-Tenant Workspace Showcase

Implement the interactive multi-tenant workspace showcase widget to visualize data isolation across companies.

### Theme & Styling Specifications
* Card outline gradients:
  * Acme Corp: Green border (`border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.1)]`).
  * TechFirm Ltd: Purple border (`border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.1)]`).
  * GlobalTrade Inc: Gold border (`border-amber-500/30 shadow-[0_0_15px_rgba(245,158,11,0.1)]`).
* Privacy badges: `bg-emerald-950/20 text-emerald-400 border border-emerald-800/40 rounded px-2 py-0.5 text-xs`.

### File Coordinates
* Component: [apps/invoice-website/components/marketing/WorkspaceShowcase.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/components/marketing/WorkspaceShowcase.tsx)

### Tasks
- [ ] **Task 2.1: Implement Workspace Showcase Container Layout**
  - Create the layout section: *"Every Company Gets Their Own Private Workspace"*.
  - Add text detailing: *"Your data never mixes with another company. Think of it as your own private office — just on the cloud."*
- [ ] **Task 2.2: Render Interactive Tenant Profile Cards**
  - Render three mock cards side-by-side representing Acme Corp, TechFirm, and GlobalTrade.
  - Display simulated user lists with specific roles: `Admin`, `Auditor`, `Loader`.
  - Embed dynamic metrics counters for each (e.g. `1,240 invoices processed`).
- [ ] **Task 2.3: Build Privacy Seal Banner**
  - Place a bottom notification banner: `🔒 Data between companies is completely sealed — no crossover, ever.` styled in a dark teal glassmorphic border.

### Verification Plan
* **Manual Verification**: Verify spacing and rendering across mobile viewports, ensuring grid wraps gracefully.
