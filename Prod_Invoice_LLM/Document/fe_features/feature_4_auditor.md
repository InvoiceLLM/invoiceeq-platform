# Feature 4: Split-Screen Auditor Review Console

Develop the read-only verification console, visual PDF coordinate viewer, and alert override dismiss handlers.

### Theme & Styling Specifications
* Bounding Box Overlays: `border border-[#10B981] bg-[#10B981] bg-opacity-10 shadow-[0_0_10px_rgba(16,185,129,0.4)]`.
* Alert Banner Cards: `bg-yellow-950/20 border border-yellow-700/50 text-yellow-200 rounded-lg`.
* Verified Details Box: Inputs must be styled as read-only fields (`bg-[#1E293B] border-[#222D3D] text-slate-300 pointer-events-none`).

### File Coordinates
* Auditor Page: [apps/invoice-fe/app/invoices/review/[id]/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/invoices/review/[id]/page.tsx)
* PDF Canvas Viewer: [apps/invoice-fe/components/audit/PdfViewerCanvas.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/audit/PdfViewerCanvas.tsx)
* Alert Console: [apps/invoice-fe/components/audit/AlertConsole.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/audit/AlertConsole.tsx)

### Tasks
- [ ] **Task 4.1: Render Document PDF Canvas**
  - Integrate a PDF reader framework (e.g. `react-pdf` or custom embed) showing original pages.
- [ ] **Task 4.2: Draw Coordinate Bounding Boxes**
  - Build absolute-positioned HTML/SVG layout overlays mapping extracted coordinates (retrieved from `GET /api/v1/invoices/{invoice_id}`) as green bounding box borders directly on top of the PDF canvas.
- [ ] **Task 4.3: Implement Read-Only Metadata Inspector**
  - Implement form fields displaying: `Vendor Name`, `Invoice Date`, `Total Amount`, `Tax Amount`, `Due Date`, and `PO Number`.
  - Set all fields to read-only/disabled.
- [ ] **Task 4.4: Code Active Alerts Review & Dismissal Actions**
  - Render the list of warning alerts (tax mismatches, duplicates, PO differences).
  - Bind the `Dismiss` button on each card to trigger a network request removing the warning from the backend `alerts` JSONB array.
  - Implement the `Mark Paid & Finalize` and `Reject Invoice` buttons to set the status on the backend.

### Verification Plan
* **Manual Verification**: Launch the review screen for a flagged invoice. Confirm all metadata inputs are read-only and clicking "Dismiss" updates the alert list and clears overlays.
