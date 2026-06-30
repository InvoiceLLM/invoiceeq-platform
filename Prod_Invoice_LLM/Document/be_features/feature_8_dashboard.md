# Feature 8: Dashboard Metrics & Analytics API

Expose aggregated database statistics and multi-dimensional filtering for backend dashboard operations.

### File Coordinates
* Router: [apps/invoice-be/routers/dashboard.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/dashboard.py)

### Tasks
- [ ] **Task 8.1: Implement Metrics Aggregate Endpoint**
  - Code `GET /api/v1/dashboard/metrics`.
  - Calculate total spend, average processing times, count of active alerts, and invoices list grouping.
  - Return explicit properties: `total_invoiced`, `paid_amount`, `outstanding_amount`, `at_risk_amount`, `spend_over_time` (series), and `top_vendors` (series).
- [ ] **Task 8.2: Code Advanced API Filters**
  - Add query parameter filters: date ranges (start/end), specific vendor names, PO numbers, and status keys.
  - Scope all queries strictly to the requesting tenant.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_dashboard.py` confirming metrics math correctness.
* **Manual Verification**: Request metrics via cURL passing date filter parameters and check the returning JSON structure matches frontend expectations.
