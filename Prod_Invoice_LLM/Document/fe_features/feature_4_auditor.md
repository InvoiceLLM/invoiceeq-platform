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

- [x] **Task 4.1: Render Document PDF Canvas**
  - Implemented via `<iframe>` pointing to `GET /api/v1/invoices/{id}/pdf` with Zoom + Rotate toolbar in `PdfViewerCanvas.tsx`.
- [x] **Task 4.2: Draw Coordinate Bounding Boxes**
  - Absolute-positioned `<div>` overlays with emerald green border + glow shadow rendered from `invoice.coordinates[]` in `PdfViewerCanvas.tsx`.
- [x] **Task 4.3: Implement Read-Only Metadata Inspector**
  - `ReadOnlyField` components display: `Vendor Name`, `Invoice Date`, `Total Amount`, `Tax Amount`, `Due Date`, `PO Number`. All fields are `pointer-events-none` + `readOnly`.
- [x] **Task 4.4: Code Active Alerts Review & Dismissal Actions**
  - `AlertConsole.tsx` renders per-alert yellow warning cards each with a `Dismiss` button calling `PUT /api/v1/audit/resolve/{id}`.
  - `Mark Paid & Finalize` and `Reject Invoice` buttons in the review page call `PUT /audit/resolve` with `status: PAID/REJECTED` and dismiss all remaining alerts.

### Verification Plan
* **Manual Verification**: Launch the review screen for a flagged invoice. Confirm all metadata inputs are read-only and clicking "Dismiss" updates the alert list and clears overlays.
