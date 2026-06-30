# Feature 7: Third-Party Connectors & Explorer View

Build integration connection toggles, folder navigation trees, and bulk file import controls.

### Theme & Styling Specifications
* Connector cards: `bg-[#151B26] border border-[#222D3D] rounded-xl p-4`.
* Status badge: Connected `bg-[#10B981]/15 text-[#10B981]`, Disconnected `bg-slate-800 text-slate-400`.
* File Tree node folder rows: `hover:bg-[#1E293B] cursor-pointer rounded px-2 py-1 text-slate-300 transition-colors`.

### File Coordinates
* Connectors Page: [apps/invoice-fe/app/connectors/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/connectors/page.tsx)
* Explorer Component: [apps/invoice-fe/components/connectors/FolderTreeExplorer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/components/connectors/FolderTreeExplorer.tsx)

### Tasks
- [ ] **Task 7.1: Build Integration Cards Grid**
  - Render configuration modules for Salesforce, SAP, QuickBooks, and Webhooks.
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
