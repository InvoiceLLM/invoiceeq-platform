# Feature Website 2 Test Suite: Multi-Tenant Workspace Showcase

Spec source: [`website_features/feature_2_showcase.md`](../../../apps/invoice-website/website_features/feature_2_showcase.md).
Scope: `components/marketing/{WorkspaceShowcase,AITeamSection,FlowsShowcaseSection,FlowsModal}.tsx`.

**Note**: like Feature 1, the tenant-isolation widget is entirely mock data (`TENANT_DATA` hardcoded array) — the "Security Probe" is a simulated `setTimeout`, not a real backend call. The one genuine cross-app integration point is `FlowsModal`, which iframes `invoice-fe`'s real `/flows` page.

---

## 1. Screen Alignment Check

| TC ID | Element | Expected Visual Spec | How to Verify |
|---|---|---|---|
| TC-WEB2-01 | Acme Corp card | Green border, `border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.1)]` | Inspect card classes when Acme tab/card active and inactive |
| TC-WEB2-02 | TechFirm Ltd card | Purple border, `border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.1)]` | Same, for TechFirm |
| TC-WEB2-03 | GlobalTrade Inc card | Gold border, `border-amber-500/30 shadow-[0_0_15px_rgba(245,158,11,0.1)]` | Same, for GlobalTrade |
| TC-WEB2-04 | Privacy badges | `bg-emerald-950/20 text-emerald-400 border border-emerald-800/40 rounded px-2 py-0.5 text-xs` | Inspect badge classes on each tenant card |
| TC-WEB2-05 | Tab row ↔ card sync | Active tab and active card highlight together | Click a tab, confirm matching card highlights; click a card, confirm matching tab highlights |
| TC-WEB2-06 | Role badges | `getRoleBadgeStyle()`: Admin=indigo, Auditor=cyan, Loader=emerald | Inspect the 3-person member list badge colors per role |
| TC-WEB2-07 | AITeamSection layout | 4 agent cards: NOVA, SENTINEL, SAGE, EVOLVE | Confirm all 4 render with correct labels/descriptions |
| TC-WEB2-08 | FlowsShowcaseSection tiles | 4 tiles: Inbound, Outbound/Vendor, Chat, Direction-Aware + "Launch Live Simulator" button + "Full Tab" link | Confirm layout and that all 6 clickable elements render |
| TC-WEB2-09 | FlowsModal | Iframe fills modal, "Open Full Screen in New Tab" link visible | Open modal, confirm iframe renders `invoice-fe`'s `/flows` page inside it |
| TC-WEB2-10 | Mobile responsiveness | 3-column tenant card grid wraps gracefully on narrow viewports | Resize to mobile width, confirm no horizontal overflow/clipping |

---

## 2. Functionality Check

| TC ID | Action | Expected Behavior |
|---|---|---|
| TC-WEB2-11 | Click a tenant tab (Acme/TechFirm/GlobalTrade) | Sets `activeTenantId`; matching card highlights |
| TC-WEB2-12 | Click a tenant card directly | Also sets `activeTenantId` (bidirectional sync with tab row) |
| TC-WEB2-13 | Click "Run Security Probe Test" | `runSecurityProbe()` — ~700ms loading state (`isTestingProbe`), then a terminal-styled result confirming the simulated `@techfirm.io` → `@acme.com` cross-tenant query was blocked with a `403 Forbidden` |
| TC-WEB2-14 | Click any of the 4 flow tiles | `onOpenModal(flow.id)` opens `FlowsModal` pre-selected to that specific flow |
| TC-WEB2-15 | Click "Launch Live Simulator" | `onOpenModal("inbound")` opens `FlowsModal` defaulted to the Inbound flow |
| TC-WEB2-16 | Click "Full Tab" link | Opens `${NEXT_PUBLIC_FE_URL}/flows` in a new tab (`target="_blank"`), no `?flow=` param, full page navigation away from the site |
| TC-WEB2-17 | Open `FlowsModal` for a specific flow | Iframe `src` = `${FE_URL}/flows?flow=<id>`; confirm `invoice-fe/app/flows/page.tsx`'s `useEffect` reads the `flow`/`tab`/`type` query param on mount and opens the matching tab (normalizes `chat`/`rag`→chat, `outbound`/`vendor`→outbound, `vendor_chat`/`direction_aware`/`direction`→vendor_chat, `inbound`→inbound) |
| TC-WEB2-18 | Click "Open Full Screen in New Tab" inside the modal | Uses the identical `flowsUrl` the iframe is already showing (same deep-link param carries over) |

---

## 3. Database Validation

| TC ID | Check |
|---|---|
| TC-WEB2-19 | `TENANT_DATA` (Acme/TechFirm/GlobalTrade, mock `Tenant ID Key`s like `t_acme_881920`) is hardcoded in `WorkspaceShowcase.tsx`. Confirm none of these mock IDs resolve to a real row in the `Tenant` table — `SELECT * FROM tenant WHERE id::text ILIKE '%acme_881920%'` (or equivalent) should return nothing. |
| TC-WEB2-20 | "Run Security Probe Test" must fire **zero** requests to `invoice-be` — confirm via Network tab. The "blocked, 403" result is a pure client-side `setTimeout`, not a real backend enforcement check today. If this is later wired to a real endpoint, a genuine cross-tenant probe must still return `403` from the backend, not just from the UI copy. |

---

## 4. Flow Validation via Log Files

Same caveat as Feature 1: no file-based logging configured in `invoice-be`; watch stdout/console output, not a literal file.

| TC ID | Check |
|---|---|
| TC-WEB2-21 | Exercise every interaction in section 2 (tab/card clicks, probe simulator, all flow tiles, both modal entry points) with `invoice-be`'s console open. Expect **zero** new log lines — nothing in this feature calls `invoice-be`. |
| TC-WEB2-22 | When `FlowsModal` opens (iframe loads `invoice-fe`'s `/flows`), check `invoice-fe`'s dev server console for the page load. Confirm no errors/warnings and a normal `GET /flows` response, not a 404/500 (would surface as a broken iframe visually too). |
