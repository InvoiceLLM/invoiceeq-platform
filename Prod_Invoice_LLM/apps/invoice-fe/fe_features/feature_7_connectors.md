# Feature 7: Third-Party Connectors & Explorer View

Build integration connection toggles, folder navigation trees, and bulk file import controls.

### Theme & Styling Specifications
* Connector cards: `bg-[#151B26] border border-[#222D3D] rounded-xl p-4`.
* Status badge: Connected `bg-[#10B981]/15 text-[#10B981]`, Disconnected `bg-slate-800 text-slate-400`.
* File Tree node folder rows: `hover:bg-[#1E293B] cursor-pointer rounded px-2 py-1 text-slate-300 transition-colors`.

### File Coordinates
* Connectors Page: [apps/invoice-fe/app/connectors/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/connectors/page.tsx) *(not yet created)*
* Integration Card Grid: [apps/invoice-fe/components/connectors/IntegrationCard.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/connectors/IntegrationCard.tsx) *(not yet created — Task 7.1 has no component file today)*
* Explorer Component: [apps/invoice-fe/components/connectors/FolderTreeExplorer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/connectors/FolderTreeExplorer.tsx) *(not yet created)*
* Proxy Routes: none exist yet under `app/api/connectors/`. Backend endpoints are already live: `get_connectors_status()`, `get_auth_url()`, `oauth_callback()`, `list_connector_files()`, `trigger_file_import()` — all currently mock data, see `be_features/feature_9_connectors.md`

### Tasks
- [ ] **Task 7.1: Build Integration Cards Grid**
  - Render configuration modules for Google Drive and Salesforce — the only two providers `routers/connectors.py` actually implements. SAP and QuickBooks were never real (not even mocked) and were removed from scope (no confirmed customer/system); Webhooks moved to its own dedicated feature (see `feature_9_webhooks.md`) rather than a connector-grid card, since it's outbound event delivery (multiple endpoints, event subscriptions, delivery logs) rather than an inbound OAuth-toggle integration like the other two.
  - Implement active connection toggles calling oauth redirection routes.
  - Display active status states based on `/api/v1/connectors/status`.
- [ ] **Task 7.2: Code Directory Folder Explorer**
  - Fetch folders and contents from `/api/v1/connectors/files/{provider}`.
  - Render an interactive tree node list with checkboxes to select items.
- [ ] **Task 7.3: Implement Bulk Import Trigger**
  - Implement a `Import Selected Files` action button.
  - Post list of chosen documents to `/api/v1/connectors/import/{provider}` and show progress toasts.

### Verification Plan
* **Manual Verification**: Open the connectors view, click connect on a card, browse the remote mock folder structure, and click import.
