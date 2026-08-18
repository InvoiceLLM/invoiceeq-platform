# Feature Website 5: Contact Us Page & Inquiries Dispatch

**Status:** Built 2026-08-17 (commit `fc48ef0`) — Tasks 5.1–5.3 landed; **Task 5.4 (automated tests) was not done.** Status lives in `website_features_tracker.md` (Gap 183, marked `[~]`); this doc is the design record.  
**Target Application:** `invoice-website`  
**Primary Notification Inbox:** `Application@infinevocloud.com`

---

## 1. Overview & Objective

Provide a dedicated, high-converting, dark-glassmorphism **Contact Us** page at `/contact` on the marketing website for sales demos, enterprise quotes, partnership inquiries, and direct customer support. Form submissions route directly to the platform's backend support engine and dispatch notifications to `Application@infinevocloud.com`.

---

## 2. File Coordinates

* **Page Route Component (new):** `apps/invoice-website/app/contact/page.tsx` — the `/contact` client page. Holds the form state (`name`, `email`, `category`, `company`, `urgency`, `message`), per-field validation errors, and the `success` state carrying the returned reference id; posts the whole payload to `/api/contact`.
* **API Proxy Route (new):** `apps/invoice-website/app/api/contact/route.ts` — one `POST` handler. Validates the `REQUIRED_FIELDS` envelope (`name`, `email`, `message`) and forwards to `${BACKEND_API_URL}/api/v1/support/contact`, returning 503 if the backend is unreachable. Unauthenticated by design, mirroring `app/api/auth/provision/route.ts`.
* **Navigation Header (edited):** `apps/invoice-website/components/marketing/Header.tsx` — `/contact` link added to both the desktop nav and the mobile drawer, using the existing `navLinkClass()` / `navCurrent()` / `drawerLinkClass()` helpers so the active indicator works.
* **Site Footer (edited):** `apps/invoice-website/components/marketing/Footer.tsx` — `/contact` link added to the footer links bar.
* **Multi-Zone routing (edited):** `apps/invoice-website/next.config.js` — `"support"` added to `feApiPrefixes` so `/api/support/*` calls made from FE-proxied pages reach `invoice-fe`. Note `/api/contact` itself is **not** proxied — it is the website's own route.

---

## 3. Functionality

1. **Dedicated `/contact` Route**:
   - Styled with website design tokens (`#050816` background, cyan `#22D3EE` & blue `#3B82F6` glows, glassmorphism cards).
   - Side panel with official contact email (`Application@infinevocloud.com` with 1-click clipboard copy), SLA guarantee (`< 2h Urgent / < 24h Standard`), and live system status indicator.
2. **Interactive Form Fields**:
   - `Full Name`: Required text.
   - `Work Email`: Required RFC-compliant email validation.
   - `Inquiry Category`: Dropdown (`SALES`, `TECHNICAL_SUPPORT`, `BILLING`, `PARTNERSHIP`, `GENERAL`).
   - `Company / Organization`: Optional text.
   - `Urgency Level`: Interactive pill selector (`LOW`, `NORMAL`, `URGENT`).
   - `Message Details`: Multi-line textarea with character validation.
3. **Submission & Tracking**:
   - Dispatches payload to Next.js API Route `app/api/contact/route.ts` which forwards to backend `POST /api/v1/support/contact`.
   - On success: renders an animated confirmation state showing tracking ID (e.g. `REF #INQ-2026-XXXX`) and SLA notice.
4. **Site-Wide Navigation Updates**:
   - `Header.tsx`: Includes "Contact Us" link in desktop navigation and mobile drawer with active indicator.
   - `Footer.tsx`: Includes "Contact Us" link in footer links bar.

---

## 4. Tasks

- [x] **Task 5.1: Create Contact Us Page Route (`app/contact/page.tsx`)** — Done 2026-08-17. Two-panel responsive layout: contact/SLA/status side panel with clipboard copy, and the validated form with the category dropdown, urgency pills, character-counted textarea, and the success card showing the returned `ticket_number`. *(This task originally said "matching `demo_screens/website_contact_us_demo.html`" — that file does not exist anywhere in this repo and never did, so the reference is removed rather than restated. The layout was built directly against the website's existing design tokens.)*
- [x] **Task 5.2: Create Next.js API Route Proxy (`app/api/contact/route.ts`)** — Done 2026-08-17. Envelope-validates `name`/`email`/`message` (422 if missing, 400 on unparseable JSON) and forwards to `POST ${BACKEND_API_URL}/api/v1/support/contact`, with 503 on an unreachable backend. Strict validation is deliberately left to the backend.
- [x] **Task 5.3: Update Header and Footer Navigation** — Done 2026-08-17. `/contact` wired into `Header.tsx` desktop nav and mobile drawer (with `aria-current` active state) and into `Footer.tsx`.
- [ ] **Task 5.4: Automated Smoke & E2E Tests** — **Not done.** `apps/invoice-website/e2e/` contains 6 specs (`billing-failed`, `billing-payu-relay`, `billing-proxy-mode`, `billing-success`, `email-mailintegration-relay`, `smoke`) and none of them reference `/contact`. No automated test covers this page at any level.

---

## 5. Verification Plan

* **Automated Test:** Run Playwright test verifying `/contact` renders, validates required fields, and submits successfully.
* **Manual Verification:** Submit test inquiry, verify assigned Reference ID, and confirm email alert received at `Application@infinevocloud.com`.

### 5.1 Actual verification state (recorded 2026-08-18)

* **Automated:** none. Task 5.4 was never done, so neither bullet above has been executed for this page.
* **Reported by the branch author, 2026-08-17:** website `tsc` clean. Not re-run in the 2026-08-18 merge-prep pass — no `node_modules` was installed in that worktree.
* **Never done:** no live submission through `/api/contact` → `POST /api/v1/support/contact` → SendGrid, so no inquiry raised by this page has been confirmed to arrive at `Application@infinevocloud.com`.
