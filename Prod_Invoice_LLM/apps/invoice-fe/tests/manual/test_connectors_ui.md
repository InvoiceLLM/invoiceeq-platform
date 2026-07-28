# Manual Test Checklist — FE Feature 7: Connectors UI

Run the dev server (`npm run dev`) with the backend running locally before executing these tests.

---

## Pre-conditions
- Backend is running.
- Mock auth is active (default role Admin, matching mock tenant).

---

## Test 1 — Settings Page Navigation
1. Navigate to `/settings`.
2. Locate the **Connectors** card.
3. Verify that the card displays "Configure" button instead of "Coming soon".
4. Click **Configure**.
5. **Expected:** Redirects to `/settings/connectors`, loading is shown, then the two integration cards (Google Drive & Salesforce) render properly.

---

## Test 2 — Integration Statuses & Cards
1. Verify the layout of the Google Drive and Salesforce cards.
2. Under "Not Configured" status:
   - Status badge is Slate grey.
   - Folder mapping section is hidden.
   - Main button is Blue: **Connect Account**.

---

## Test 3 — OAuth Connection Flow Simulation
1. Click **Connect Account** on the **Google Drive** card.
2. **Expected:**
   - Loading spinner is displayed on the button.
   - Simulation fetches `/api/connectors/auth-url/google_drive`, then triggers the callback `/api/connectors/callback/google_drive?code=mock_code`.
   - Card updates automatically: status changes to **Active** (green badge).
   - "Connect Account" button changes to a red **Disconnect** button.
   - Folder Mappings section (Inbound AP & Outbound AR) is now visible.

---

## Test 4 — Folder Mapping Configuration & Explorer
1. Click the chevron button `>` next to **Inbound AP** mapping.
2. **Expected:** The **Google Drive Explorer** panel slides up below the cards.
   - Displays "Root" folder path.
   - Displays files (`invoice_acme_hardware.pdf`, `globex_services_statement.pdf`) and folders (`Ingested_Invoices`).
3. Click the **Ingested_Invoices** folder.
4. **Expected:** Folder history is updated, path displays `Root / Ingested_Invoices`, files list updates, and "Back" button becomes visible.
5. Click **Map current folder** link at the top-right of the navigator.
6. **Expected:** Folder name ("Ingested_Invoices") is set in local storage, explorer closes, and "Inbound AP" folder status displays "Ingested_Invoices".

---

## Test 5 — Directory Browsing and Bulk Import
1. Open the Explorer panel again for Google Drive Inbound AP.
2. Use checkboxes to select `invoice_acme_hardware.pdf` and `globex_services_statement.pdf`.
3. Click **Import Selected**.
4. **Expected:**
   - Button shows a loading spinner.
   - Import requests are posted sequentially in the background (`POST /api/connectors/import/google_drive` with payload `{file_id: ...}`).
   - Progress notice appears: "Import request queued!" (green badge).
   - Checkboxes are cleared.

---

## Test 6 — Disconnect Action
1. Click **Disconnect** on the **Google Drive** card.
2. **Expected:**
   - Status updates back to "Not Configured".
   - Folder mappings section is hidden.
   - Mapped folder names are cleared from local storage.
