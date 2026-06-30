# Frontend (invoice-fe) Test Cases

This document details the test suite for the Next.js client frontend application.

## Feature 1: Global Theme & Core Shell Layout
### TC-FE-01: Dark Mode Canvas & Responsive Navigation Sidebar
* **Goal**: Validate dark mode CSS variables, background styling, and responsive drawer toggling.
* **How to Test**: Load the site, inspect `body` CSS for `#0B0F19` background. Resize to mobile width, assert layout changes and hamburger menu functions.

### TC-FE-02: User Role-Based Navigation Scoping
* **Goal**: Verify sidebar navigation items match user role.
* **How to Test**: Login as role `Viewer`. Assert that AI Trainer and Connectors pages are hidden.

---

## Feature 2: Dashboard Analytics Command Center
### TC-FE-03: Real-Time Metrics & Trend Graphs Rendering
* **Goal**: Ensure dashboard graphs render analytical time series fetched from API.
* **How to Test**: Access `/dashboard`. Verify card panels load correct metrics and Recharts elements populate SVG graphics.

### TC-FE-04: Recent Invoices Data Grid Navigation
* **Goal**: Verify invoice rows navigate to detailed pages.
* **How to Test**: Click on a table row. Assert browser redirects to `/invoices/review/{id}`.

---

## Feature 3: File Ingestion Portal & Active Tagging
### TC-FE-05: Drag-and-Drop Uploader State
* **Goal**: Validate file selection, drop area highlights, and file size validation.
* **How to Test**: Drag a valid PDF file onto the drop-zone. Assert file item displays with a loader, and tags input field is interactive.

### TC-FE-06: Tag Entry and Batch Upload Submission
* **Goal**: Submit multiple files with active metadata tags.
* **How to Test**: Add tags `[2026, Q2]`, upload files. Check that the outbound request POST body contains files and tags array.

---

## Feature 4: Split-Screen Auditor Review Console
### TC-FE-07: PDF Canvas Bounding Box Overlays
* **Goal**: Check that absolute green bounding box overlays render on top of the PDF pages at correct positions.
* **How to Test**: Open an invoice audit review page. Inspect overlay elements for computed styles (absolute coordinates).

### TC-FE-08: Alert Dismissal UI Actions
* **Goal**: Verify warning banners can be dismissed, updating the database.
* **How to Test**: Click the "Dismiss Warning" button on a discrepancy alert card. Assert the alert card disappears and a success toast notifications pop up.

---

## Feature 5: Semantic Chat Assistant & SQL Audit Drawer
### TC-FE-09: Chat Stream Message Bubbles & Citations
* **Goal**: Render chat streams with user/assistant bubbles and clickable citation pills.
* **How to Test**: Type a question in the chat panel. Verify streaming output displays, and clicking `[page X]` citation highlights the document page.

### TC-FE-10: Executed SQL Audit Accordion
* **Goal**: Check that the SQL Drawer renders formatted code blocks.
* **How to Test**: Ask a query. Click "Show SQL Query" accordion. Verify formatted SQL code displays with a functioning "Copy" button.

---

## Feature 6: AI Trainer Interactive Sandbox
### TC-FE-11: Transient Template Testing Portal
* **Goal**: Upload invoices into the sandbox and run conversational correction rules.
* **How to Test**: Upload a test PDF in sandbox. Type correction *"Field invoice_date is wrong"* in chat, and check that key-values update.

### TC-FE-12: Commit Template Action
* **Goal**: Commit training session corrections to database registry.
* **How to Test**: Click "Save Template Rules" button. Verify successful redirect and a success banner.

---

## Feature 7: Third-Party Connectors & Explorer View
### TC-FE-13: Connector Credentials Validation
* **Goal**: Verify client-side field validation for ERP/Email integrations.
* **How to Test**: Open Gmail Connector card, attempt to submit blank password. Assert error message displays.

### TC-FE-14: Connector Toggle Sync
* **Goal**: Activate/deactivate connectors in real time.
* **How to Test**: Toggle a connector on. Assert network status switches to active.
