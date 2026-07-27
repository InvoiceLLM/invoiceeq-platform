# Feature 8: Dashboard Metrics & Analytics API

Expose aggregated database statistics and multi-dimensional filtering for backend dashboard operations.

### File Coordinates
* Router: [apps/invoice-be/routers/dashboard.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/dashboard.py) → `GET /dashboard/metrics` → `get_dashboard_metrics()`; `GET /dashboard/trainer-impact` → `get_trainer_impact()`; `GET /dashboard/insights` → `get_dashboard_insights()`

### Functionality
`get_dashboard_metrics()` pulls every tenant-scoped `Invoice` matching the optional `start_date`/`end_date`/`vendor_name`/`po_number`/`status` filters into memory, then does one pass over the rows in Python (not SQL aggregates) to build: `total_invoiced` (sum of all `grand_total`), `paid_amount` (status `PAID`), `outstanding_amount` (status `COMPLETED`/`AUDIT_REQUIRED`/`PROCESSING`), `at_risk_amount` (status `AUDIT_REQUIRED` only), `active_alerts_count` (sum of `len(sa_alerts)`), `spend_over_time` (grouped by `invoice_date`, falling back to `created_at.date()` if unset), `top_vendors` (grouped by `vendor_name`, sorted descending, FE takes the top 5), and `invoices_by_status` counts. `average_processing_time` is a real measurement (`completed_at - created_at`, averaged over invoices where `completed_at` is set), not the earlier hardcoded mock.

`get_trainer_impact()` (Gap 28) returns `rules_trained` (Global/vendor-specific `ExtractionTemplate` counts), `vendors_needing_rules` (≥2 flagged invoices, no template yet), and a real weekly `audit_rate_trend`.

`get_dashboard_insights()` (Gap 30) generates the AI-written strategic-recommendations text `fe_features/feature_2_dashboard.md` Gap 4 needs. It recomputes a small, LLM-scoped subset of the same aggregates (total invoiced, at-risk amount, audit rate, top 5 vendors by spend, top 5 vendors needing a rule) into a JSON context blob, then makes one `get_llm().with_structured_output(DashboardInsightsSchema)` call explicitly instructed to ground every recommendation in a number from that blob and never invent one. Each insight has a `title`, `detail`, and `severity` (`info`/`warning`/`critical`). Result is cached in Redis (`dashboard_insights:{tenant_id}`, 1-hour TTL, same inline-client pattern as Task 6.11's chat answer cache) so the LLM isn't called on every dashboard load. A failed/erroring LLM call degrades to `{"insights": []}` rather than a 500.

### Tasks
- [x] **Task 8.1: Implement Metrics Aggregate Endpoint**
- [x] **Task 8.2: Code Advanced API Filters**
- [x] **Task 8.3: Trainer impact metrics** — done as Gap 28, `GET /dashboard/trainer-impact` (separate endpoint, not folded into `/metrics`). Rendered by `fe_features/feature_2_dashboard.md` Task 2.5 / FE Gap 21.
- [x] **Task 8.4: Actionable insights generation** *(Gap 30, 2026-07-27)* — `GET /dashboard/insights`, described above. Rendered by `fe_features/feature_2_dashboard.md` FE Gap 4.

### Verification Plan
* **Automated Tests**: `uv run pytest tests/test_dashboard.py` — includes `test_dashboard_insights_empty`, `test_dashboard_insights_grounded` (asserts the real computed numbers actually reach the LLM prompt), and `test_dashboard_insights_llm_failure_returns_empty`.
* **Manual Verification**: Live-verified against real Azure OpenAI + real invoice data — first call ~16-35s (LLM round-trip), second call ~0.35s (Redis cache hit); output referenced real dollar amounts and audit-rate percentages from the tenant's actual data, with no raw JSON field names leaking into the prose after a prompt-wording fix.
