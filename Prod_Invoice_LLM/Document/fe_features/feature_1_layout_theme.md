# Feature 1: Global Theme & Core Shell Layout

Setup the visual system design tokens and the primary grid layout shell containing sidebar and top bar navigation.

### Theme & Styling Specifications
All features must strictly adhere to these color mappings. Configure CSS tokens inside `apps/invoice-fe/styles/globals.css`:
```css
:root {
  --bg-main: #0B0F19;               /* Primary dark navy canvas */
  --bg-panel: rgba(21, 27, 38, 0.75);/* Glassmorphic panel base background */
  --border-default: #222D3D;        /* Panel separations and card borders */
  --text-primary: #E2E8F0;          /* High contrast light grey headings */
  --text-muted: #94A3B8;            /* Dull slate grey labels and captions */
  
  /* Brand/Status Accents */
  --accent-green: #10B981;          /* Save, Success, Complete indicators */
  --accent-red: #EF4444;            /* Reject, Error warnings */
  --accent-blue: #3B82F6;           /* Processing, Active selections */
  --accent-yellow: #F59E0B;         /* Warnings and Audit required states */
}
```

### File Coordinates
* Styles: [apps/invoice-fe/styles/globals.css](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/styles/globals.css)
* Layout Shell: [apps/invoice-fe/components/layout/Shell.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Shell.tsx)
* Sidebar Component: [apps/invoice-fe/components/layout/Sidebar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/layout/Sidebar.tsx)

### Tasks
- [ ] **Task 1.1: Initialize CSS Variables & Tailwind Config**
  - Add design tokens to `globals.css` and extend Tailwind config with custom colors (e.g. `bg-main`, `bg-panel`, `border-default`).
  - Set default body backgrounds (`bg-[#0B0F19] text-slate-200`) and modern typography settings (e.g. Inter or Roboto font face).
- [ ] **Task 1.2: Build Responsive Navigation Sidebar**
  - Create the sidebar navigation component showing: Dashboard, Ingest, Invoices, Settings, and Help.
  - Apply glassmorphism borders (`border-r border-[#222D3D] backdrop-blur-md`).
  - Add active routing highlights (`bg-[#1E293B] text-white border-l-2 border-[#3B82F6]`).
- [ ] **Task 1.3: Build Header Top Bar**
  - Include search field, notifications tray icon, help indicator, and user profile metadata card (`Alex R. / Acme Corp.`).
  - Configure profile dropdown to retrieve details from Clerk/Auth0 context.

### Verification Plan
* **Manual Verification**: Run `npm run dev` inside `apps/invoice-fe` and inspect the layout elements. Verify layout responsiveness and correct styling.
