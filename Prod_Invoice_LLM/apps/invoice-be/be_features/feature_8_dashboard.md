# Feature 8: Dashboard Metrics & Analytics API

Expose aggregated database statistics and multi-dimensional filtering for backend dashboard operations.

### File Coordinates
* Router: [apps/invoice-be/routers/dashboard.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/dashboard.py) → `GET /dashboard/metrics` → `get_dashboard_metrics()`

### Functionality
`get_dashboard_metrics()` pulls every tenant-scoped `Invoice` matching the optional `start_date`/`end_date`/`vendor_name`/`po_number`/`status` filters into memory, then does one pass over the rows in Python (not SQL aggregates) to build: `total_invoiced` (sum of all `grand_total`), `paid_amount` (status `PAID`), `outstanding_amount` (status `COMPLETED`/`AUDIT_REQUIRED`/`PROCESSING`), `at_risk_amount` (status `AUDIT_REQUIRED` only), `active_alerts_count` (sum of `len(sa_alerts)`), `spend_over_time` (grouped by `invoice_date`, falling back to `created_at.date()` if unset), `top_vendors` (grouped by `vendor_name`, sorted descending, FE takes the top 5), and `invoices_by_status` counts. `average_processing_time` is currently a **hardcoded mock** (`4.5` if any invoices exist, else `0.0`) — not a real measurement. There is no trainer-impact data (`rules_trained_count`, `audit_rate_trend`, `vendors_needing_rules`) yet — that's Task 8.3 below.

### Tasks
- [ ] **Task 8.1: Implement Metrics Aggregate Endpoint**
  - Code `GET /api/v1/dashboard/metrics`.
  - Calculate total spend, average processing times, count of active alerts, and invoices list grouping.
  - Cache the heavy aggregated response in Azure Cache for Redis to improve dashboard load times and reduce PostgreSQL load.
  - Return explicit properties: `total_invoiced`, `paid_amount`, `outstanding_amount`, `at_risk_amount`, `spend_over_time` (series), and `top_vendors` (series).
- [ ] **Task 8.2: Code Advanced API Filters**
  - Add query parameter filters: date ranges (start/end), specific vendor names, PO numbers, and status keys.
  - Scope all queries strictly to the requesting tenant.
- [ ] **Task 8.3: Trainer impact metrics** *(new — makes the trainer's value visible, drives adoption)*
  - Extend `GET /api/v1/dashboard/metrics` (or a new `GET /api/v1/dashboard/trainer-impact`) to return: `rules_trained_count` (Global + per-vendor `ExtractionTemplate` rows for the tenant), `audit_rate_trend` (invoices landing in `AUDIT_REQUIRED` before vs. after each rule's `created_at`, per vendor), and `vendors_needing_rules` (vendors with a high recurring-correction rate per `feature_7_audit.md` Task 7.4 but no `ExtractionTemplate` row yet).
  - Rendered by `fe_features/feature_2_dashboard.md` Task 2.5.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_dashboard.py` confirming metrics math correctness.
* **Manual Verification**: Request metrics via cURL passing date filter parameters and check the returning JSON structure matches frontend expectations.
