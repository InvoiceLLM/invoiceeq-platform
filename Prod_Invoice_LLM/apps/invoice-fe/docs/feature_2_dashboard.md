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
* Invoice Table: [apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/RecentInvoicesTable.tsx) — **moving to `feature_4_auditor.md`'s new `/invoices` queue screen, see Dashboard/Audit split note below; listed here only because it's still physically on this page today.**
* Metrics Proxy Route: [apps/invoice-fe/app/api/dashboard/metrics/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/dashboard/metrics/route.ts) → forwards to `GET /dashboard/metrics` (`docs/feature_8_dashboard.md`)
* Trainer Impact Panel: [apps/invoice-fe/components/dashboard/TrainerImpactPanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/TrainerImpactPanel.tsx) → `GET /api/dashboard/trainer-impact`
* Actionable Insights Panel: [apps/invoice-fe/components/dashboard/ActionableInsightsPanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/dashboard/ActionableInsightsPanel.tsx) → `GET /api/dashboard/insights` (`docs/feature_8_dashboard.md` Gap 30)

### Dashboard/Audit split (2026-07-29, addresses Gap 28)
The invoice-level table + filters below are moving off this page entirely, onto a new dedicated `/invoices` queue screen (`feature_4_auditor.md` Task 4.9) — Dashboard's job is overview (metrics/trends/insights), not browsing/paging the full invoice list, which is a separate action-oriented workflow. This also avoids Dashboard getting overcrowded once outbound's own invoice table (`feature_2.1_vendor_flow_dashboard.md`) needs a place to live. In its place, Dashboard gets one small **`NeedsAttentionWidget.tsx`** — top 5-10 `AUDIT_REQUIRED` rows (plus outbound `NEEDS_REVIEW` rows if Service Flow has shipped), each linking straight to its review screen. See Task 2.7 below.

### Functionality
`FilterBar.tsx` is fully client-side: `handleChange()` updates local `FilterState{vendorName, dateRange, tag, status}` and calls the parent's `onFilterChange` on every change (there's no server round-trip per filter — the page presumably re-filters the already-fetched invoice list); `handleSaveFilters()` persists it to `localStorage["invoice_dashboard_filters"]` and auto-restores it on mount. `MetricsGrid.tsx` renders 4 `KpiCard`s off the raw `feature_8_dashboard.md::get_dashboard_metrics()` response, draws the spend trendline as a hand-built interactive SVG polyline (no chart library), and reads `extraction_accuracy`/`average_processing_time` directly from that response — both are real backend-computed values now, not client-side approximations. `ClientPerformanceChart.tsx` takes `vendors.slice(0, 5)` and renders horizontal bars scaled to the largest vendor's total — also no chart library, hand-built with `<div>` widths.

`ActionableInsightsPanel.tsx` (Gap 4) fetches its own `GET /dashboard/insights` independently of the main metrics call, same pattern as `TrainerImpactPanel.tsx`. Renders each returned insight (`title`/`detail`/`severity`) as a card with a severity-colored icon/border (`critical`=rose, `warning`=amber, `info`=blue). Shows a "not enough data yet" message when the list is empty (new tenant, or the backend's LLM call failed) rather than an error state — an empty insights list is a normal, expected response shape, not a failure.

### Tasks
- [ ] **Task 2.1: Implement Filter Bar Controls**
  - Bind dropdown states for Client (Vendors), Date Range (This Month, Last 30 Days), Invoice Tags (e.g., `#Hardware`), and Status.
  - Implement a `Save Filter` button to persist active layouts in browser local storage.
- [ ] **Task 2.2: Build Invoice Overview & Predictions Cards**
  - Code KPI metric displays for: Total Invoiced, Paid amount (with percentage), Outstanding total, and At-Risk values (invoices past due or with active alerts).
  - Embed the linear trendline spend graph and circular progress gauge indicator for extraction accuracy.
- [ ] **Task 2.3: Build Client Performance Bar Chart**
  - Integrate a bar graph (e.g. using Recharts or Chart.js) displaying the top 5 vendors by billing totals.
- [x] **Task 2.4: Code Recent Invoices Table**
  - Code table binding columns: `Invoice #`, `Client` (Vendor Name), `Issue Date`, `Amount`, `AI Status` (Verified, Review Required, Processing), and `Actions`.
  - Bind the `...` actions button to navigate to the detailed Auditor Review Console (`/invoices/review/{id}` — originally pointed at a nonexistent `/audit` route, fixed 2026-07-27 alongside FE Gap 26).
- [x] **Task 2.4.1: Status sub-tabs, scroll-lock, pagination** *(FE Gaps 5/11/12, 2026-07-27)*
  - All/Paid/Pending/Rejected tabs, client-side filtered. Table wrapped in a `max-height: 320px` scroll-locked container with a sticky header. Previous/Next pagination (8 rows/page) over the tab-filtered list.
- [x] **Task 2.5: Trainer Impact Panel** — done as FE Gap 21 (2026-07-27). `TrainerImpactPanel.tsx` renders rule-count tiles, a weekly audit-rate bar trend, and a "Vendors Needing a Rule" list deep-linking into a pre-scoped Trainer sandbox session for that vendor.
- [x] **Task 2.6: Actionable Insights Panel** *(Gap 4, 2026-07-27)* — `ActionableInsightsPanel.tsx`, described above. Backend: `docs/feature_8_dashboard.md` Gap 30.
- [x] **Task 2.7 (Gap 28, Dashboard/Audit split) — done 2026-07-29:**
  - Built `NeedsAttentionWidget.tsx` (top 8 `AUDIT_REQUIRED` rows, direction-agnostic — ready for outbound rows once that ships) and added it to `page.tsx`.
  - **Redundant-code removal done**: `dashboard/page.tsx` no longer has `activeTab`/`currentPage`/`totalCount`/`isInvoicesLoading`/`fetchInvoicesPage`/`PAGE_SIZE`/`tabToStatusParams` or the `RecentInvoicesTable` import/JSX. **`FilterBar.tsx` was kept** (correction from the original task wording) — it still filters `MetricsGrid`/the chart, just no longer an invoice list alongside it.
  - Tasks 2.4/2.4.1 above stay checked as historical record of what was built, but their described behavior physically relocates per this task — not a regression, a move.

### Verification Plan
* **Manual Verification**: Run Next.js dashboard view, toggle filters, and verify that mock details update accordingly. Check color contrast matches the dark layout.
* **Task 2.7 verification**: `npx tsc --noEmit` clean; real dev server confirmed `/dashboard` returns 200 with "Needs Attention" rendering and zero console errors; grep confirms `dashboard/page.tsx` has no `RecentInvoicesTable` reference and no leftover pagination state. **Not yet verified**: real metrics/filter behavior against live backend data (no BE running in this pass).
