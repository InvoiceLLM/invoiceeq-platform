# Manual Test Checklist — FE Feature 10: Settings Screen (Service Flow)

Run the dev server (`npm run dev`) with the BE running locally before executing these tests.

---

## Pre-condition
Backend is running, mock auth active (no token → Admin role, `MOCK_TENANT_ID`).

---

## Test 1 — Page loads and shows defaults
1. Navigate to `/settings`.
2. **Expected:** "Settings" header visible. "Service Flow" section shows:
   - *Receive Invoices* toggle **ON** (blue).
   - *Send Invoices* toggle **OFF** (grey).
   - *Outbound Sender Email* field empty.
   - No non-Admin banner visible.

---

## Test 2 — Save outbound sender email
1. Type `invoices@acme.com` in the Outbound Sender Email field and click **Save**.
2. **Expected:** Toast "Settings saved." appears. Field retains the entered email.

---

## Test 3 — Client-side guard: enable Send Invoices with empty email
1. Clear the Outbound Sender Email field.
2. Click the *Send Invoices* toggle.
3. **Expected:** Toggle stays OFF. Inline error appears: *"Outbound Sender Email is required before enabling Send Invoices."* No network call made.

---

## Test 4 — Billing plan gate: upgrade modal appears (non-pro_combined tenant)
1. Ensure the test tenant's `billing_plan` is `"free"` or `"pro"` (check DB or use a test seed).
2. Fill in a valid sender email, click **Save**.
3. Click the *Send Invoices* toggle.
4. **Expected:** **Combined Pro Upgrade Modal** opens with plan details and *Upgrade Now* link. Toggle stays OFF.
5. Click **Cancel**. Modal closes, toggle stays OFF.

---

## Test 5 — Happy path: enable Send Invoices (pro_combined tenant)
1. Set the test tenant's `billing_plan` to `"pro_combined"` in the DB.
2. Fill in sender email, click Save.
3. Click the *Send Invoices* toggle.
4. **Expected:** Toggle flips ON (violet). Toast "Settings saved." appears. `GET /api/settings/service-flow` now returns `send_invoices_enabled: true`.

---

## Test 6 — Toggle Receive Invoices off
1. Click the *Receive Invoices* toggle.
2. **Expected:** Toggle flips OFF (grey). Toast "Settings saved." appears.
3. Click it again → flips back ON.

---

## Test 7 — Non-Admin role (read-only)
1. Add `Authorization: Bearer test_viewer` to requests (or temporarily hard-code role to `"Viewer"` in `page.tsx`).
2. Navigate to `/settings`.
3. **Expected:**
   - Amber banner: *"These settings are read-only for your role. Contact an Admin to make changes."*
   - Both toggles and the email field are visually dimmed (`opacity-50`), cursor shows `not-allowed`.
   - Clicking a toggle does nothing (disabled).

---

## Test 8 — Settings persist on page reload
1. As Admin, set both toggles to a specific state and a sender email.
2. Hard-reload the page (`Ctrl+Shift+R`).
3. **Expected:** Same toggle states and email value restored from the backend.
