# Feature 1: Global Theme & Core Shell Layout

Setup the visual system design tokens and the primary grid layout shell containing sidebar and top bar navigation.

### Theme & Styling Specifications
All features must strictly adhere to these color mappings. Configure CSS tokens inside `apps/invoice-fe/styles/globals.css`:
```css
:root {
  --bg-main: #0B0F19;               /* Primary dark navy canvas */
  --bg-panel: rgba(21, 27, 38, 0.75);/* Glassmorphic panel base background */
  --border-default: #222D3D;        /* Panel separations and card borders */
  --text-primary: #E2E8F0;          /* High contrast light grey headings */
  --text-muted: #94A3B8;            /* Dull slate grey labels and captions */
  
  /* Brand/Status Accents */
  --accent-green: #10B981;          /* Save, Success, Complete indicators */
  --accent-red: #EF4444;            /* Reject, Error warnings */
  --accent-blue: #3B82F6;           /* Processing, Active selections */
  --accent-yellow: #F59E0B;         /* Warnings and Audit required states */
}
```

### File Coordinates
* Styles: [apps/invoice-fe/styles/globals.css](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/styles/globals.css)
* Layout Shell: [apps/invoice-fe/components/layout/Shell.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Shell.tsx) — composes `Sidebar` + `Header` around a scrollable `<main>`
* Sidebar Component: [apps/invoice-fe/components/layout/Sidebar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Sidebar.tsx)
* Header Component: [apps/invoice-fe/components/layout/Header.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Header.tsx)

### API Call Path (applies to every FE feature, not repeated per-file below)
The FE never calls `invoice-be` directly. `lib/apiClient.ts` is an axios instance with `baseURL: "/api"` (same-origin); each `app/api/**/route.ts` Next.js Route Handler runs server-side and calls `lib/backendProxy.ts::proxyJson(request, path)`, which forwards method/body/query string to `${BACKEND_API_URL}/api/v1${path}` and passes through the `Authorization` header. So a spec elsewhere saying "dispatch to `/api/v1/invoices/upload`" means: FE calls `apiClient.post("/invoices/upload")` → same-origin `app/api/invoices/upload/route.ts` → proxied server-side to the real backend endpoint.

### Functionality
`Sidebar.tsx` hardcodes the nav list (`Dashboard → /dashboard`, `Ingest → /ingestion`, `AI Trainer → /trainer`, `Chat → /chat`, `Settings → /settings`, `Help → /help`) and highlights the active route via `usePathname()`; its footer also hardcodes the all-zero tenant UUID (`00000000-...`), matching `dependencies.py::get_tenant_context()`'s local/test fallback context (see `docs/feature_1_auth.md`) rather than reading a real session. There is no standalone "Invoices" nav item — one used to point at `/audit`, a route that never existed, and was removed rather than repointed (see `fe_features_tracker.md` Gap 28); the invoice review screen is reached per-invoice from Dashboard/Ingestion row actions instead. `Header.tsx`'s search input, help button, and notification bell are still static — no handlers wired. The profile dropdown is now wired to real Clerk session data via `useUser()`/`useClerk()` (`fe_features_tracker.md` Gap 66): name, org, role, and email come from `user.firstName`/`lastName`/`unsafeMetadata.orgName`/`unsafeMetadata.role`/`primaryEmailAddress`, falling back to the original hardcoded placeholder values (`Alex R.` / `Acme Corp.` / `Admin` / `admin@acme.com`) only when that Clerk data isn't set. Sign Out calls a real `handleSignOut()` — backend logout proxy call, then Clerk `signOut()`, then redirect to the website's `/login`.

> **Note — Help Center (undocumented until now):** the Sidebar's `Help → /help` link is not just a placeholder; `app/help/page.tsx` is a real, built page — a searchable help center with a topic list (left) and article pane (right), client-side filtering by title/keywords/body text over section content imported from `app/help/content/trainer-guide.tsx` and `app/help/content/auditor-guide.tsx`. It has no feature spec of its own; noted here since this is where its Sidebar entry is documented.

### Tasks
- [x] **Task 1.1: Initialize CSS Variables & Tailwind Config**
  - Add design tokens to `globals.css` and extend Tailwind config with custom colors (e.g. `bg-main`, `bg-panel`, `border-default`).
  - Set default body backgrounds (`bg-[#0B0F19] text-slate-200`) and modern typography settings (e.g. Inter or Roboto font face).
- [x] **Task 1.2: Build Responsive Navigation Sidebar**
  - Create the sidebar navigation component showing: Dashboard, Ingest, AI Trainer, Chat, Settings, and Help (no standalone Invoices item — see Functionality above).
  - Apply glassmorphism borders (`border-r border-[#222D3D] backdrop-blur-md`).
  - Add active routing highlights (`bg-[#1E293B] text-white border-l-2 border-[#3B82F6]`).
- [x] **Task 1.3: Build Header Top Bar**
  - Include search field, notifications tray icon, help indicator, and user profile metadata card.
  - Profile dropdown retrieves details from Clerk (`useUser()`), with fallback placeholders when Clerk metadata is unset; Sign Out wired to real Clerk `signOut()` + backend logout.

### Verification Plan
* **Manual Verification**: Run `npm run dev` inside `apps/invoice-fe` and inspect the layout elements. Verify layout responsiveness and correct styling.
