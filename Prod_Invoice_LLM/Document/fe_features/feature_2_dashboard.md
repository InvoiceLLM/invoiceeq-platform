# Feature 2: Dashboard Analytics Command Center

Construct the Bento-box analytics dashboard showing financial overview cards, client rankings, filter states, and recent invoices listings.

### Theme & Styling Specifications
* Grid cards must use the glassmorphic panel base background (`bg-[#151B26] bg-opacity-75 border border-[#222D3D] rounded-xl`).
* Charts must use custom colors matching the theme variables (e.g. Area chart gradient from `#3B82F6` to `#0B0F19`, bar graphs utilizing `#94A3B8`).

### File Coordinates
* Dashboard Page: [apps/invoice-fe/app/dashboard/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/dashboard/page.tsx)
* Metrics Components: [apps/invoice-fe/components/dashboard/MetricsGrid.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/MetricsGrid.tsx)
* Invoice Table: [apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx)

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

### Verification Plan
* **Manual Verification**: Run Next.js dashboard view, toggle filters, and verify that mock details update accordingly. Check color contrast matches the dark layout.
