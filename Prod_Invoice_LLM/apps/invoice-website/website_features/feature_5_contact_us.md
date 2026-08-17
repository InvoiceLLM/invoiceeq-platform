# Feature Website 5: Contact Us Page & Inquiries Dispatch

**Status:** Planned / Architecture Verified  
**Target Application:** `invoice-website`  
**Primary Notification Inbox:** `Application@infinevocloud.com`

---

## 1. Overview & Objective

Provide a dedicated, high-converting, dark-glassmorphism **Contact Us** page at `/contact` on the marketing website for sales demos, enterprise quotes, partnership inquiries, and direct customer support. Form submissions route directly to the platform's backend support engine and dispatch notifications to `Application@infinevocloud.com`.

---

## 2. File Coordinates

* **Page Route Component:** `apps/invoice-website/app/contact/page.tsx`
* **API Proxy Route:** `apps/invoice-website/app/api/contact/route.ts`
* **Navigation Header:** `apps/invoice-website/components/marketing/Header.tsx`
* **Site Footer:** `apps/invoice-website/components/marketing/Footer.tsx`
* **Interactive Demo Prototype:** `demo_screens/website_contact_us_demo.html`

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

- [ ] **Task 5.1: Create Contact Us Page Route (`app/contact/page.tsx`)**
  - Implement full responsive layout matching `demo_screens/website_contact_us_demo.html`.
- [ ] **Task 5.2: Create Next.js API Route Proxy (`app/api/contact/route.ts`)**
  - Validate body and forward to `POST ${BACKEND_API_URL}/api/v1/support/contact`.
- [ ] **Task 5.3: Update Header and Footer Navigation**
  - Wire `/contact` in `Header.tsx` (desktop nav + mobile drawer) and `Footer.tsx`.
- [ ] **Task 5.4: Automated Smoke & E2E Tests**
  - Add Playwright spec verifying navigation, form validation, and successful dispatch.

---

## 5. Verification Plan

* **Automated Test:** Run Playwright test verifying `/contact` renders, validates required fields, and submits successfully.
* **Manual Verification:** Submit test inquiry, verify assigned Reference ID, and confirm email alert received at `Application@infinevocloud.com`.
