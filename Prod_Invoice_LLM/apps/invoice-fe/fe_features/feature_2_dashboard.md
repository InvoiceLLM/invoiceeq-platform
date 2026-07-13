# Feature 2: Dashboard Analytics Command Center

Construct the Bento-box analytics dashboard showing financial overview cards, client rankings, filter states, and recent invoices listings.

### Theme & Styling Specifications
* Grid cards must use the glassmorphic panel base background (`bg-[#151B26] bg-opacity-75 border border-[#222D3D] rounded-xl`).
* Charts must use custom colors matching the theme variables (e.g. Area chart gradient from `#3B82F6` to `#0B0F19`, bar graphs utilizing `#94A3B8`).

### File Coordinates
* Dashboard Page: [apps/invoice-fe/app/dashboard/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/dashboard/page.tsx)
* Filter Bar: [apps/invoice-fe/components/dashboard/FilterBar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/FilterBar.tsx)
* KPI Card: [apps/invoice-fe/components/dashboard/KpiCard.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/KpiCard.tsx)
* Metrics Grid: [apps/invoice-fe/components/dashboard/MetricsGrid.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/MetricsGrid.tsx)
* Client Performance Chart: [apps/invoice-fe/components/dashboard/ClientPerformanceChart.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/ClientPerformanceChart.tsx)
* Invoice Table: [apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx)
* Metrics Proxy Route: [apps/invoice-fe/app/api/dashboard/metrics/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/dashboard/metrics/route.ts) → forwards to `GET /dashboard/metrics` (`be_features/feature_8_dashboard.md`)

### Functionality
`FilterBar.tsx` is fully client-side: `handleChange()` updates local `FilterState{vendorName, dateRange, tag, status}` and calls the parent's `onFilterChange` on every change (there's no server round-trip per filter — the page presumably re-filters the already-fetched invoice list); `handleSaveFilters()` persists it to `localStorage["invoice_dashboard_filters"]` and auto-restores it on mount. `MetricsGrid.tsx` renders 4 `KpiCard`s off the raw `feature_8_dashboard.md::get_dashboard_metrics()` response, draws the spend trendline as a hand-built interactive SVG polyline (no chart library), and computes "Extraction Accuracy" client-side as `99.4 - (active_alerts_count * 0.1)` clamped to `[90.0, 99.8]` — **this is a client-side approximation, not a real backend accuracy metric**. `ClientPerformanceChart.tsx` takes `vendors.slice(0, 5)` and renders horizontal bars scaled to the largest vendor's total — also no chart library, hand-built with `<div>` widths.

### Tasks
- [ ] **Task 2.1: Implement Filter Bar Controls**
  - Bind dropdown states for Client (Vendors), Date Range (This Month, Last 30 Days), Invoice Tags (e.g., `#Hardware`), and Status.
  - Implement a `Save Filter` button to persist active layouts in browser local storage.
- [ ] **Task 2.2: Build Invoice Overview & Predictions Cards**
  - Code KPI metric displays for: Total Invoiced, Paid amount (with percentage), Outstanding total, and At-Risk values (invoices past due or with active alerts).
  - Embed the linear trendline spend graph and circular progress gauge indicator for extraction accuracy.
- [ ] **Task 2.3: Build Client Performance Bar Chart**
  - Integrate a bar graph (e.g. using Recharts or Chart.js) displaying the top 5 vendors by billing totals.
- [ ] **Task 2.4: Code Recent Invoices Table**
  - Code table binding columns: `Invoice #`, `Client` (Vendor Name), `Issue Date`, `Amount`, `AI Status` (Verified, Review Required, Processing), and `Actions`.
  - Bind the `...` actions button to navigate to the detailed Auditor Review tab or view details.
- [ ] **Task 2.5: Trainer Impact Panel**
  - Render `rules_trained_count`, `audit_rate_trend` (per-vendor before/after chart), and `vendors_needing_rules` from `GET /api/v1/dashboard/metrics` (or a dedicated `/dashboard/trainer-impact`), per `be_features/feature_8_dashboard.md` Task 8.3.
  - Bind each `vendors_needing_rules` entry to open a pre-scoped Trainer sandbox session (Vendor scope) for that vendor.

### Verification Plan
* **Manual Verification**: Run Next.js dashboard view, toggle filters, and verify that mock details update accordingly. Check color contrast matches the dark layout.
