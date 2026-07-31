# Feature Website 1 Test Suite: Landing Page & Core Shell

Spec source: [`website_features/feature_1_landing.md`](../../../apps/invoice-website/website_features/feature_1_landing.md).
Scope: `app/page.tsx`, `components/marketing/{Header,Hero,BenefitsStrip,MouseSpotlight,Footer}.tsx`, `app/layout.tsx`.

**Note on this feature's blast radius**: everything here is client-rendered with hardcoded mock data (`HERO_CAPABILITIES`, `SAMPLE_INVOICES`) — no component in this file makes a network call to `invoice-be`. That shapes sections 3 and 4 below into absence-checks rather than positive-assertion checks.

---

## 1. Screen Alignment Check

| TC ID | Element | Expected Visual Spec | How to Verify |
|---|---|---|---|
| TC-WEB1-01 | Page canvas | Background `#0B0F19` | Load `/`, inspect computed `background-color` on `<body>`/root wrapper |
| TC-WEB1-02 | Panel borders (e.g. pipeline-demo card) | `#222D3D` | Inspect border color on `Hero.tsx`'s `#pipeline-demo` card |
| TC-WEB1-03 | Hero heading | Gradient text, `bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-sky-400 to-emerald-400` | Inspect class list on "Automated Invoice Intelligence" heading |
| TC-WEB1-04 | Primary buttons | Emerald `bg-[#10B981] hover:bg-[#059669] text-white` | Check "Start Free Trial" / "Get Started Free" button classes |
| TC-WEB1-05 | Secondary buttons | Ghost style, `border border-[#222D3D] hover:bg-slate-900` | Check secondary CTA classes |
| TC-WEB1-06 | Header scroll state | Darkens once scrolled past 20px (`scrolled` state) | Scroll page, confirm header background changes at the 20px threshold, reverts above it |
| TC-WEB1-07 | Mobile nav drawer | Full-width drawer with Features/Login + CTA | Resize to mobile viewport, open hamburger, verify drawer layout |
| TC-WEB1-08 | Hero capability pills | 4 pills (NOVA/SENTINEL/SAGE/EVOLVE), one highlighted at a time | Watch `highlightedPillIndex` auto-cycle every 1.5s; hover shows tooltip per agent |
| TC-WEB1-09 | Pipeline demo card | 3D tilt on mouse-move (`rotateX`/`rotateY`) + scroll-driven parallax tilt/scale | Move mouse across `#pipeline-demo`; scroll page and observe separate parallax effect |
| TC-WEB1-10 | Benefits strip | Row of icon + title + accent-color callouts below hero | Confirm `BenefitsStrip()` renders directly under Hero section |
| TC-WEB1-11 | Site footer | Brand mark + nav links + `lucide-react` icons (`FileText`, `Shield`, `Lock`, `ExternalLink`) | Confirm `Footer()` renders on `/`, `/login`, `/signup` alike (mounted once in `app/layout.tsx`) |
| TC-WEB1-12 | Mouse spotlight | Cursor-follow glow effect | Move mouse anywhere on any page; confirm glow tracks cursor (mounted site-wide, not landing-only) |

---

## 2. Functionality Check

| TC ID | Action | Expected Behavior |
|---|---|---|
| TC-WEB1-13 | Click "Architecture Flow" nav link (has "Live" badge) | Calls `onOpenFlowsModal()` if provided by parent; else falls through to `#architecture-flows` anchor |
| TC-WEB1-14 | Click "Features" nav link | Scrolls to `#features` (matches `WorkspaceShowcase.tsx`'s `id="features"`) |
| TC-WEB1-15 | Click "Login" nav link / "Get Started Free" CTA | Routes to `/login` |
| TC-WEB1-16 | Click a sample invoice tile (`INV-9842` / `FRT-1048` / `SUB-7721`) | `runLiveSimulation(invoice)` resets and animates 4 stages every 600ms: Secure Upload → NOVA Extraction → SENTINEL Review → Verified Result (`activeStep` 0→3) |
| TC-WEB1-17 | Click "Line Items Breakdown" / "Agent JSON Consensus" inspector tabs | Renders `selectedInvoice.taxBreakdown` rows vs. pretty-printed `selectedInvoice.rawJson` respectively |
| TC-WEB1-18 | Click "Re-Run Extraction Test" | Re-triggers `runLiveSimulation` on the currently selected invoice |
| TC-WEB1-19 | Click "Simulate Pipeline" CTA | Scrolls to `#pipeline-demo` |
| TC-WEB1-20 | Click any mobile drawer link | Drawer closes (`mobileMenuOpen` → false) after navigating |

---

## 3. Database Validation

| TC ID | Check |
|---|---|
| TC-WEB1-21 | Exercise every interaction in section 2 (sample switches, tab switches, re-run button, all nav/CTA clicks) as an anonymous visitor, then confirm **zero** rows were created/touched in `Invoice`, `Tenant`, or any other table. All data shown (`SAMPLE_INVOICES`, taxBreakdown, rawJson) is hardcoded in the component — none of it is a real extraction result. |

---

## 4. Flow Validation via Log Files

**Caveat before running this section**: `invoice-be`'s `main.py` only calls `logging.getLogger(__name__)` — there is no `logging.basicConfig`/file handler configured anywhere in the backend. Output goes to stdout only (the `uvicorn`/dev-server console locally, or `docker logs`/Container App log stream in Azure). "Log files" don't literally exist yet — treat every log check in this test suite as "watch the process's stdout," not "tail a file."

| TC ID | Check |
|---|---|
| TC-WEB1-22 | With `invoice-be`'s console open, exercise every Feature 1 interaction. Expect **zero** new HTTP requests in the browser Network tab and therefore **zero** new log lines from `invoice-be`. Any request/log line appearing here means a future edit introduced an unintended backend coupling into what should be a fully static/mock landing experience. |
| TC-WEB1-23 | Browser DevTools console shows no uncaught errors/warnings while scrolling, hovering pills, switching samples, or opening/closing the mobile drawer. |
