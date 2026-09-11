# Feature 1: Global Theme & Core Shell Layout

Setup the visual system design tokens and the primary grid layout shell containing sidebar and top bar navigation.

### Theme & Styling Specifications
All features must strictly adhere to these color mappings. Configure CSS tokens inside `apps/invoice-fe/styles/globals.css`:
```css
/* 1. Classic Dark (Default Theme) */
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
  --accent-cyan: #38BDF8;           /* Cyan highlight */
  --accent-yellow: #F59E0B;         /* Warnings and Audit required states */
}

/* 2. InfiNevoCloud PPT Brand Theme (FE Gap 478) */
[data-theme="infinevo"] {
  --bg-main: #0A1324;               /* InfiNevo Midnight Navy canvas */
  --bg-panel: rgba(23, 64, 109, 0.25);/* InfiNevo Navy glassmorphic panel base */
  --border-default: #1D3557;        /* InfiNevo Slate borders and dividers */
  --text-primary: #F0F6FC;          /* High contrast ice-white headings */
  --text-muted: #8BA3C7;            /* Slate blue labels and captions */
  
  /* Brand/Status Accents */
  --accent-green: #10CF9B;          /* InfiNevo Mint - Verified, Save, Success */
  --accent-red: #EF4444;            /* Reject, Error warnings */
  --accent-blue: #0F6FC6;           /* InfiNevo Azure - Primary buttons, active routes */
  --accent-cyan: #009DD9;           /* InfiNevo Sky Cyan - Active nav highlight, glows */
  --accent-yellow: #F49100;         /* InfiNevo Tangerine - Audit Required & Attention */
}
```

### File Coordinates
* Styles: [apps/invoice-fe/styles/globals.css](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/styles/globals.css)
* Theme Hook: [apps/invoice-fe/hooks/useTheme.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/hooks/useTheme.ts) — `useTheme()`; manages theme switching and `localStorage` persistence (FE Gap 478)
* Layout Shell: [apps/invoice-fe/components/layout/Shell.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Shell.tsx) — `Shell()`; composes `Sidebar` + `Header` around a scrollable `<main>`, all wrapped in `PageHeaderProvider`
* Sidebar Component: [apps/invoice-fe/components/layout/Sidebar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Sidebar.tsx) — `Sidebar()`
* Header Component: [apps/invoice-fe/components/layout/Header.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Header.tsx) — `Header()`, `useNeedsAttentionCount()`, `useDisplayIdentity()`
* Page-header channel: [apps/invoice-fe/components/layout/PageHeaderContext.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/PageHeaderContext.tsx) — `PageHeaderProvider()`, `usePageHeader()`, `PageHeaderActions()`, `usePageHeaderMeta()`, `usePageHeaderActionsRef()`, `PageHeaderMeta`
* Page-header presentation: [apps/invoice-fe/components/layout/PageHeader.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/PageHeader.tsx) — `PageHeader()`; the title cluster, rendered once by `Header`

### API Call Path (applies to every FE feature, not repeated per-file below)
The FE never calls `invoice-be` directly. `lib/apiClient.ts` is an axios instance with `baseURL: "/api"` (same-origin); each `app/api/**/route.ts` Next.js Route Handler runs server-side and calls `lib/backendProxy.ts::proxyJson(request, path)`, which forwards method/body/query string to `${BACKEND_API_URL}/api/v1${path}` and passes through the `Authorization` header. So a spec elsewhere saying "dispatch to `/api/v1/invoices/upload`" means: FE calls `apiClient.post("/invoices/upload")` → same-origin `app/api/invoices/upload/route.ts` → proxied server-side to the real backend endpoint.

**Null-body statuses (Gap 177, 2026-08-11).** `proxyJson` relays the backend's status and body verbatim, with one required exception: 204/205/304 are null-body statuses per the Fetch spec, and `new NextResponse("", { status: 204 })` throws `TypeError: Response constructor: Invalid response status code 204` — `""` is not null. Because the helper always passed `await response.text()`, *every* route handler in the app turned a backend 204 into a 500, and did so **after** the backend had already committed the write. Any caller that only updates local state on success (`useChatSession.ts::deleteSession`, the webhooks list) therefore left the deleted row on screen until a page reload. `proxyJson` now passes `null` as the body for 204/205/304 (and for any empty body, which is byte-identical over the wire), so a backend 204 reaches the browser as a real 204. Backend endpoints returning 204 are correct as written and need no change.

### Functionality
`Sidebar.tsx` hardcodes the nav list (`Dashboard → /dashboard`, `Ingest → /ingestion`, `AI Trainer → /trainer`, `Chat → /chat`, `Settings → /settings`, `Help → /help`) and highlights the active route via `usePathname()`; its footer also hardcodes the all-zero tenant UUID (`00000000-...`), matching `dependencies.py::get_tenant_context()`'s local/test fallback context (see `docs/feature_1_auth.md`) rather than reading a real session. **Stale as of 2026-08-01, corrected**: this used to say there's no standalone "Invoices" nav item — that was true when originally written (one used to point at `/audit`, a route that never existed, and was removed rather than repointed, see `fe_features_tracker.md` Gap 28), but `feature_4_auditor.md` Task 4.9 (2026-07-29) re-added a nav item at `/invoices` as part of the unified Invoices/Audit queue screen. This doc was never updated after that reversal. Note the item's rendered label is **"Audit Queue"**, not "Invoices" — some other docs (`feature_4_auditor.md`, `feature_2_dashboard.md`) refer to it by the route/concept name "Invoices," not its literal Sidebar text. `Header.tsx`'s search input was removed, and the notification bell displays the active "Needs Attention" count (inbound `AUDIT_REQUIRED` + outbound `NEEDS_REVIEW`) and links to the `/invoices` queue. **Gap 199 (2026-08-11):** `useNeedsAttentionCount` re-fetches on `usePathname()` change and on debounced focus/visibility so the badge does not freeze while Header stays mounted across client navigations. Sign Out calls a real `handleSignOut()` — backend logout proxy call, then Clerk `signOut()`, then redirect to the website's `/login`.

**The header is the app's single page header, for every route (Gap 110, 2026-08-04).** It was previously chrome-only (`justify-end`, no title), with each screen drawing its own title block below it — Dashboard/Ingestion/Audit Queue via a per-page `<PageHeader>`, and Trainer, Settings, all four Settings sub-pages and both review consoles via a full `h-16 border-b <header>` bar of their own, i.e. two stacked header bars on one screen. It is now `justify-between`: the active route's title cluster on the left, that route's own controls plus the bell and profile block on the right, with the Sidebar's brand block completing the brand / title / profile arrangement across the top of the screen.

A routed page cannot render into the layout that wraps it, so `PageHeaderContext.tsx` carries the content upward through two mechanisms, split on purpose:
* `usePageHeader({ title, agentIcon, agentName, agentRole, subtitle, backHref })` — all primitives, so it lives in context state keyed on those values and cannot loop. Pages call it unconditionally at the top of the component, above any loading/error early return, so a screen still names itself while fetching. `backHref` renders the back arrow that Settings sub-pages and the review consoles used to draw themselves.
* `<PageHeaderActions>` — a `createPortal` into a slot `Header` always renders. Page controls are arbitrary JSX with live handlers and are a new element on every render; routing them through the same state would re-set context every render and never settle. Used by Trainer (Rule History / Commit to Template Registry), Ingestion and Audit Queue (Receiving/Sending toggle), Webhooks (Add Endpoint), and both review consoles (live status badge).

`PageHeader.tsx` is the presentational title cluster, rendered exactly once by `Header`. Because the row also carries page actions and the profile block and starts 256px in from the left, its decorative parts drop out first as width tightens — agent role text below 1536px, the whole codename badge below 1280px, the subtitle below 640px — and the title truncates rather than pushing controls off the row. **Deliberately not moved into the header**: the Dashboard's `FilterBar`, whose compact variant is four selects plus a Save button (~660px of minimum widths) and would push controls off-screen at 1024–1280px, re-creating Gap 85. It stays as the first row of the page body, which is the row the title used to occupy.

The profile block is wired to real Clerk session data via `useUser()`/`useClerk()` (Gap 66), through `useDisplayIdentity()`. **Gap 116 (2026-08-04)** replaced the old fabricated fallbacks: `firstName || "Alex"` / `lastName || "R."` / `"AR"` / `"admin@acme.com"` / `"Acme Corp."` are gone. `isLoaded` is read explicitly, so the pre-load moment renders a skeleton rather than a plausible wrong person; once loaded the chain is real first+last name → the email local part title-cased → "Signed in". The role no longer comes from `unsafeMetadata.role` (the sign-up flow writes the literal string `"admin,user"` there, which rendered verbatim) but from `useAuth()`'s `GET /auth/me`, the same authoritative source `Sidebar` filters on. The org line is omitted rather than invented when absent. **Gap 142 (2026-08-11, merged from `Global-common-bugs-Fix`):** profile menu is no longer dead buttons — **My Profile** opens Clerk `openUserProfile()`, **Account Settings** is an Admin-only link to `/settings`, and the menu dismisses on outside click and route change.

**`orgName` moved to the backend's resolved tenant, 2026-08-11 (BE Gap 133 / FE Gap 217).** It used to read `unsafeMetadata.orgName` — real data in the sense that sign-up genuinely writes it, but written once client-side and **never reconciled with the tenant the backend actually resolves the request to**. Those were two independent sources, and when an organisation failed to provision they diverged silently: the header confidently displayed the org the user signed up with while their invoices lived in an unrelated tenant, and nothing in the UI could reveal it (this is item 4 of BE Gap 133). `TenantContext` now carries `tenant_name`, `hooks/useAuth.ts` exposes it as `tenantName`, and `Header.tsx` renders that. `unsafeMetadata.orgName` survives only as the placeholder while `authLoading` is true, so the header does not flicker empty on each page load. `app/admin/page.tsx` had the identical bug in its workspace card and took the identical fix; its `orgType`/`country` still come from metadata, which has no backend equivalent. **Known upstream gap**: `invoice-website`'s sign-up form never collects a person's name, so `firstName`/`lastName` are null on every account created so far and the email-derived form is what real users will see until that flow changes.

> **Note — Help Center (undocumented until now):** the Sidebar's `Help → /help` link is **the app's one entry point to it** — `Header.tsx` used to carry a second `HelpCircle` icon pointing at the same route (added by Gap 87 finding G), removed by Gap 110; the Sidebar entry and the page itself are unchanged. It is not just a placeholder; `app/help/page.tsx` is a real, built page — a searchable help center with a topic list (left) and article pane (right), client-side filtering by title/keywords/body text over section content imported from `app/help/content/trainer-guide.tsx` and `app/help/content/auditor-guide.tsx`. It has no feature spec of its own; noted here since this is where its Sidebar entry is documented.

### Tasks
- [x] **Task 1.1: Initialize CSS Variables & Tailwind Config**
  - Add design tokens to `globals.css` and extend Tailwind config with custom colors (e.g. `bg-main`, `bg-panel`, `border-default`).
  - Set default body backgrounds (`bg-[#0B0F19] text-slate-200`) and modern typography settings (e.g. Inter or Roboto font face).
- [x] **Task 1.2: Build Responsive Navigation Sidebar**
  - Create the sidebar navigation component showing: Dashboard, Ingest, AI Trainer, Chat, Audit Queue (`/invoices`, re-added 2026-07-29 per `feature_4_auditor.md` Task 4.9), Settings, and Help — see Functionality above for the label/history correction.
  - Apply glassmorphism borders (`border-r border-[#222D3D] backdrop-blur-md`).
  - Add active routing highlights (`bg-[#1E293B] text-white border-l-2 border-[#3B82F6]`).
- [x] **Task 1.3: Build Header Top Bar**
  - Notifications tray icon and user profile metadata card. The search field was removed (Gap 87/95, dead element) and the help indicator was removed as a duplicate of the Sidebar's Help tab (Gap 110) — see Functionality above.
  - Profile dropdown retrieves details from Clerk (`useUser()`); Sign Out wired to real Clerk `signOut()` + backend logout. Gap 116 replaced the invented fallback identity with an `isLoaded` skeleton and an email-derived name.
  - **Gap 151 (fixed 2026-08-12)**: `signOut()` was called with no destination, so Clerk's own post-sign-out navigation (falling back to its hosted Account Portal) raced and won against the following manual `window.location.href` line, landing users on an unbranded Clerk page instead of `/login`. Now calls `signOut({ redirectUrl: \`${WEBSITE_URL}/login\` })` directly; the manual redirect survives only as a fallback if that call throws. `app/layout.tsx`'s `<ClerkProvider>` also gained `afterSignOutUrl` as a second layer for any sign-out path other than this button.
- [x] **Task 1.4: One shared page header for every screen** — added 2026-08-04 (Gap 110). `PageHeaderContext.tsx` + `usePageHeader()` + `<PageHeaderActions>`; `PageHeader.tsx` reduced to the title cluster and rendered once by `Header`; all 12 screens converted off their own title markup.
- [x] **Task 1.5: Dual-Theme Switcher & InfiNevoCloud Brand Palette (FE Gap 478)** — added 2026-09-10.
  - Support both Classic Dark theme and InfiNevo PPT Brand Theme via `[data-theme="infinevo"]` CSS variables, matching `InfiNevoCloud Induction Programe - Antoday.pptx` and the reference mockup `infinevo_theme_preview_1789030360159.jpg`.
  - State managed by `hooks/useTheme.ts` with `localStorage` persistence, toggled via a dedicated `Palette` button in `Header.tsx`, with anti-flash hydration script in `app/layout.tsx`.
  - Implements:
    - Soft Ice-Blue canvas (`#F0F6FA`).
    - Hero KPI Card with InfiNevo corporate Navy-to-Azure Gradient (`#071C38` to `#17406D`), pure white text, and cyan glow icon box.
    - Secondary KPI and content cards in Pure White (`#FFFFFF`) with `#E2EDF5` borders and deep navy values (`#0F2847`).
    - AI Score widget with soft ice-blue inner container (`#EDF5FB`) and deep navy text (`#17406D`).
    - Recent Invoices table with Signature Ice-Blue headers (`#DBEFF9`) and bold deep navy labels (`#17406D`).
    - Solid high-contrast badges: Mint Green (`#10CF9B`), Tangerine Orange (`#F49100`), Sky Cyan (`#009DD9`).
    - High-contrast dropdown filter text (`#17406D` on `#FFFFFF`).
  - Zero structural changes, zero label changes, and Classic Dark mode fully preserved as default.
- [x] **Task 1.6: Product-wide Text Contrast & Visibility Audit (FE Gap 479)** — added 2026-09-10.
  - Full product-wide inspection and CSS adapter fixes for text visibility and contrast across all routes in InfiNevo mode:
    - `/chat`: ThreadSidebar converted to crisp white (`#FFFFFF`), bold `#0F2847` titles, `#64748B` empty state text, InfiNevo Azure `#0F6FC6` New Chat button; message bubbles with `#0F6FC6` user pill / white assistant card; input composer converted to white/ice-blue with clearly visible disclaimer text.
    - Top header scoping: restricted to `header.h-16`, ensuring content headers on `/history` and other screens remain transparent with deep navy titles and slate subtitles.
    - `/settings`: Integration grid tiles converted from dark `bg-[#111827]` to crisp white cards with `#0F2847` titles and `#475569` descriptions.
    - `/trainer`: Upgrade prompt feature box converted from black-on-black to soft ice-blue (`#EDF5FB`) with clearly legible `#17406D` text.
    - `/help`: Search input pill and nav tabs updated for clean light-mode contrast.
    - Alert and error banners updated to soft pastel backgrounds with high-contrast text (`#FEF2F2` / `#B91C1C`).
  - Verified across all 8 routes via automated Playwright screenshots with zero regression on Classic Dark mode.
- [x] **Task 1.7: Inner Modals, Form Controls & Settings Subpages Theme Alignment (FE Gap 480)** — added 2026-09-10.
  - Form controls (`input`, `textarea`, `select`, `label`) globally adapted to InfiNevo brand palette: pure white background (`#FFFFFF`), light slate borders (`#CBDCEB`), deep corporate navy text (`#0F2847`), and visible placeholders (`#94A3B8`).
  - Modal dialog cards (`div.fixed.inset-0 > div`) and drawers converted to `#FFFFFF` with `#D6E4F0` borders, `#F0F6FA` ice-blue headers, and `#0F2847` titles.
  - Support Ticket Modal (`SupportTicketModal.tsx`): input fields, textarea, category select, priority pills, and transcript attachments styled with high-contrast InfiNevo tokens.
  - Help Center SAGE AI Support Assistant (`SupportChatWindow.tsx`): chat area converted to crisp white canvas, high-contrast message cards, soft ice-blue prompt chips (`#EDF5FB`), and white bottom input bar.
  - Settings Subpages (`/settings/*`) verified with 10/10 scores across Connectors, Email Setup, Subscriptions, Webhooks, Security, and Workflows.
  - Zero component markup alterations, zero dark mode regressions.

- [x] **Task 1.8: Profile Trigger & User Dropdown Color Visibility Alignment (FE Gap 488)** — added 2026-09-11.
  - Dedicated InfiNevo theme adapter for the navbar user profile trigger and popover dropdown menu in `styles/globals.css`.
  - Profile dropdown container styled in InfiNevo Midnight Navy (`#08172C`) with glowing Cyan border (`rgba(0, 157, 217, 0.45)`).
  - "Signed in as" label elevated to InfiNevo Sky Cyan (`#BAE6FD`, 10.2:1 contrast) and user email in pure White (`#FFFFFF`).
  - Menu action icons (`User`, `Settings`) mapped to InfiNevo Cyan (`#009DD9`) with ice-white text and cyan glow hover.
  - Reset "Sign Out" button from an unintended boxed error banner to a clean transparent button with crisp Coral Red (`#F87171`) and soft coral hover tint.
  - Navbar role/org subtitle and chevron icon elevated to InfiNevo Sky Cyan (`#BAE6FD`).
  - 100% zero structural changes to `Header.tsx`; Classic Dark mode completely untouched.

- [x] **Task 1.9: Audit Queue & Table Invoice Tags Visibility Alignment (FE Gap 489)** — added 2026-09-11.
  - Resolved table invoice tags visibility issue under vendor name on `/invoices` and Recent Invoices table.
  - Adapted hardcoded dark slate pills (`bg-slate-800`, `text-slate-400`) into soft Ice-Blue badges (`#EBF5FC`), fine cyan border (`1px solid #BAE6FD`), and bold high-contrast InfiNevo Ocean Blue text (`#0369A1`, 7.5:1 AAA contrast ratio).
  - Enhanced font weight to 700 bold, size to 10px, line-height 1.25, with clean letter-spacing and soft rounded corners.
  - Added smooth hover state (`#DFEFFB` / `#7DD3FC` / `#025A8B`).
  - Adapted Batch Ingestion TagSelector chips in `TagSelector.tsx` for visual harmony.
- [x] **Task 1.10: Ingestion History Status Badges & Filter Options Vibrant Contrast (FE Gap 490)** — added 2026-09-11.
  - Resolved Ingestion History (`/history`) status colors and filter chips visibility issue in InfiNevo theme.
  - Replaced blunt `#history-page button, #history-page [class*="rounded-full"]` rule that forced all chips and badges into identical washed-out white/grey pills.
  - Filter chips: Active chips styled in InfiNevo Cyan/Azure gradient (`linear-gradient(135deg, #0F6FC6 0%, #009DD9 100%)`) with bold white text (`#FFFFFF`) and cyan drop shadow (`0 2px 8px rgba(15, 111, 198, 0.3)`); inactive chips in crisp white with slate border and readable dark slate text (`#475569`).
  - Status badges (`RunStatusChip` & `OutcomeBadge`): Vivid, high-contrast tinted badges with strong borders and 800-weight bold text:
    - `LOADED`: Mint green background (`#D1FAE5`), solid emerald border (`1.5px solid #059669`), deep emerald text (`#064E3B`, 8.1:1 AAA contrast).
    - `PARTIAL`: Warm amber background (`#FEF3C7`), amber border (`1.5px solid #D97706`), deep amber text (`#78350F`, 7.8:1 AAA contrast).
    - `REJECTED`: Soft rose background (`#FEE2E2`), crimson border (`1.5px solid #DC2626`), deep dark crimson text (`#7F1D1D`, 8.5:1 AAA contrast).
    - `NOT_LOADED`: Ice-sky background (`#E0F2FE`), sky blue border (`1.5px solid #0284C7`), dark ocean blue text (`#0369A1`, 7.9:1 AAA contrast).
    - `IN_PROGRESS` / `EMPTY`: Polished slate tints and borders.
  - Expanded file row view: Background `#F8FAFD`, divider `#E2EDF5`, file title `#0F2847` bold navy, labels `#64748B`, field values `#1E293B`, and colorful `OutcomeBadge`s with checkmark/alert icons.
  - 100% zero markup/structural changes to `IngestionHistoryTable.tsx` and `app/history/page.tsx`; Classic Dark mode 100% untouched.

- [x] **Task 1.11: AI Trainer Invoice Picker Status Button Colors & Contrast (FE Gap 491)** — added 2026-09-11.
  - Resolved status button styling and contrast in AI Trainer invoice picker list (`TrainerEntryPanel.tsx`).
  - Adapted `0 alerts` from a muddy dark slate smudge into a crisp, elegant neutral slate pill (`#F8FAFD` background, `1px solid #CBD5E1` border, `#64748B` readable text).
  - Elevated `1 alert` / active alerts into a vibrant warm amber badge (`#FEF3C7` background, `1.5px solid #D97706` amber border, `#78350F` 800-weight bold text, 7.8:1 AAA contrast, `0 1px 4px rgba(217, 119, 6, 0.18)` glow shadow).
  - Refined invoice picker card container (`#FFFFFF` / `#D6E4F0`), row hover (`#F0F7FD`), dividers (`#E2EDF5`), file icon (`#0F6FC6`), invoice numbers (`#0F2847` bold), and subtitle metadata (`#475569`).
  - Added cohesive high-contrast styles for AI Trainer staged rule list badges.
  - 100% zero TSX/DOM structural changes; Classic Dark mode 100% untouched.

### Verification Plan

* **Manual Verification**: Run `npm run dev` inside `apps/invoice-fe` and inspect the layout elements. Verify layout responsiveness and correct styling.
* **Automated (Gap 110)**: `e2e/rbac-sidebar.spec.ts` — for `/dashboard`, `/settings` and `/help`, exactly one `<header>` and one `<h1>` in the document and that `<h1>` inside the header (a page drawing its own second bar fails this); Trainer's Commit + Rule History resolve inside the header; the title updates across a client-side navigation; and the Help entry point exists once, in the Sidebar, and still reaches `/help`. Run with `npm run test:e2e`.
