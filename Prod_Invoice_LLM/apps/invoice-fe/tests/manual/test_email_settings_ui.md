# Manual Test Checklist — FE Feature 8: Email Settings UI

Run the dev server (`npm run dev`) and make sure the backend is active before running these manual checks.

---

## Pre-conditions
- Backend is running.
- Mock auth is active (role Admin, matching default tenant ID `00000000-0000-0000-0000-000000000000`).

---

## Test 1 — Settings Page Entry
1. Navigate to `/settings`.
2. Locate the **Email Ingestion & Delivery** card.
3. Verify that the card displays "Configure" button instead of "Coming soon".
4. Click **Configure**.
5. **Expected:** Redirects to `/settings/email`, page header says "Email Ingestion & Delivery", and all cards render successfully.

---

## Test 2 — Inbound Ingestion Address Card
1. Check the card displaying "Your Inbound Ingestion Address".
2. Verify the email format contains the current tenant ID: `00000000-0000-0000-0000-000000000000@invoices.invoice-ai.com`.
3. Click the copy button next to the email address.
4. **Expected:** The copy icon changes to a green checkmark (`Check`) indicating success. Paste the clipboard contents anywhere to verify the address matches.

---

## Test 3 — Allowed Inbound Senders CRUD
1. Under "Allowed Inbound Senders" card, enter `invalid-email` into the text box.
2. Click **Add**.
3. **Expected:** Client-side email validation rejects the input, displaying: "Please enter a valid email address."
4. Enter `partner@domain.com` into the text box.
5. Click **Add**.
6. **Expected:**
   - Loading indicator is shown.
   - Senders list updates with a new entry: `partner@domain.com`.
   - Success toast appears: "Email address added successfully!".
7. Add a second allowed sender `contact@vendor.org`.
8. Check that both addresses render properly with individual trash icons.
9. Click the trash icon next to `partner@domain.com`.
10. **Expected:**
    - Deletion request is sent (`DELETE /api/email/settings/email-senders/[sender_id]`).
    - The row disappears from the listing.
    - Success toast displays: "Email address removed successfully."

---

## Test 4 — Outbound Invoicing Delivery Configuration
1. Under "Outbound Invoicing Delivery", type `not-an-email` into the input.
2. Click **Save Settings**.
3. **Expected:** Client-side validation triggers, displaying: "Please enter a valid email format."
4. Enter `billing@mycompany.com` and click **Save Settings**.
5. **Expected:**
   - Saved configuration is posted via `PUT /api/settings/service-flow`.
   - Success banner appears: "Outbound sender email updated successfully!".
6. Refresh the page (`F5`).
7. **Expected:** Initial outbound email settings are loaded, and the input field successfully shows `billing@mycompany.com`.
