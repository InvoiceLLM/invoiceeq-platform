# Feature 8.1: Service Flow — Outbound Dashboard

Extends [feature_8_dashboard.md](feature_8_dashboard.md). **Implemented 2026-07-29** — all tasks complete (8.1.1/8.1.3/8.1.4 landed with Features 2.1/7.1; 8.1.2 and the test suite in this pass).

AR mirror of the existing AP metrics endpoint: total invoiced to customers, amount collected, outstanding receivables, top customers, verification accuracy, real average time-to-payment.

### File Coordinates (planned)
* New router: `apps/invoice-be/routers/outbound_dashboard.py` — `get_outbound_dashboard_metrics()`.
* Model: `apps/invoice-be/models.py::Invoice` — two new additive columns.
* Existing, unmodified: `apps/invoice-be/routers/dashboard.py` — not imported from, not edited. Filtering logic is duplicated against `flow_direction == "OUTBOUND"` rather than adding a direction parameter to the existing endpoint.
* New: `routers/outbound_dashboard.py::list_outbound_invoices()` — `GET /outbound-dashboard/invoices`, its own paginated list endpoint (limit/offset/`X-Total-Count`, `customer_name`/`start_date`/`end_date`/`status` filters), duplicating `routers/invoices.py`'s pagination pattern rather than editing it. **Correction (2026-07-29):** an earlier pass proposed adding a `flow_direction` param directly to the existing `GET /invoices`, but that contradicts this whole effort's own stated rule (`docs/architecture/System_Journey_Developer_Guide.md` Part 3: "Zero edits to `routers/invoices.py`, `audit.py`, `dashboard.py`") — reverted in favor of a genuinely separate endpoint, consistent with how the metrics endpoint above is already built.
* Feeds `invoice-fe`'s unified Invoices/Audit queue screen (see `feature_4.1_vendor_flow_auditor.md`, FE) — **not** the Dashboard. The Dashboard/Audit split (2026-07-29) moved all invoice-list UI off Dashboard entirely; only the metrics grid split remains there.

### Functionality

**Metrics (mirrors inbound's shape, AR semantics):**
- `total_invoiced_out`, `amount_collected` (`PAID` sum), `outstanding_receivables` (`SENT`/`NEEDS_REVIEW`/`UPLOADED` sum), `at_risk_receivables` (overdue sum, reusing `feature_7.1`'s read-time overdue computation — no new persisted status).
- `top_customers` (mirrors `top_vendors`), `invoices_by_status` counts.
- `verification_accuracy` — same concept as `extraction_accuracy`: % of outbound invoices that reached `VERIFIED` with zero alerts on the first pass.
- `average_days_to_payment` — real elapsed time, `paid_at - sent_at`, computed the same honest way as this session's `average_processing_time` fix (excluded from the average if either timestamp is missing, never estimated). Requires two new additive `Invoice` columns: `sent_at`, `paid_at` (nullable, set when those transitions actually happen in the outbound confirm-send / mark-paid endpoints).

**Screen behavior — split-screen, not a tab toggle:**
- **Only one service active** (Receive-only or Send-only): single, undivided view — Receive-only tenants see exactly today's Dashboard, unchanged. Send-only tenants see only the outbound metrics as their sole view.
- **Both services active:** the Dashboard divides into two halves shown simultaneously — left: Receiving (today's metrics), right: Sending (this feature's metrics) — no click/toggle needed to see both. This is a deliberate difference from Ingestion/Auditor, which use a tab (one side visible at a time, since those are action screens); Dashboard is a passive overview where seeing both totals at once is the more useful default.
- No combined/net number anywhere on this screen (e.g. no single "net cash position" card) — that comparison stays a Chat-only capability, per the earlier design decision.

### Explicitly deferred
- A combined "net position" view/card — Chat-only for now.
- Persisted `OVERDUE` status — reuses `feature_7.1`'s read-time computation, no new scheduled job.

### Tasks
- [x] **Task 8.1.1:** Add `sent_at`, `paid_at` columns to `Invoice` — done 2026-07-29, bundled into Feature 2.1's migration (`c4d5e6f7a8b9`) since that feature's own confirm-send endpoint needed `sent_at` immediately.
- [x] **Task 8.1.2: Done 2026-07-29.** `routers/outbound_dashboard.py::get_outbound_dashboard_metrics()` — `GET /outbound-dashboard/metrics`, added to the existing outbound router (no new file, no import from and no edit to `routers/dashboard.py`). Filters `start_date`/`end_date`/`customer_name`/`status`, always scoped `tenant_id` + `flow_direction == "OUTBOUND"`. Returns `total_invoiced_out`, `amount_collected`, `outstanding_receivables`, `at_risk_receivables`, `average_days_to_payment`, `verification_accuracy`, `active_alerts_count`, `revenue_over_time`, `top_customers`, `invoices_by_status`. Same aggregate split as inbound post-Gap-29: SQL `SUM`/`COUNT`/`GROUP BY` for the money/ranking/series figures, one narrow 4-column scan (`status`, `sa_alerts`, `sent_at`, `paid_at`) for the two derived metrics. Three decisions worth recording, since the spec above predates Feature 2.1 actually existing:
  - **`outstanding_receivables` includes `VERIFIED`**, not just the `SENT`/`NEEDS_REVIEW`/`UPLOADED` written above. `VERIFIED` became a real persisted status in Feature 2.1 (extracted cleanly, awaiting confirm-send); excluding it would mean `total_invoiced_out != amount_collected + outstanding_receivables`, i.e. money in no bucket at all. `PROCESSING_OCR`/`EXTRACTING_DATA`/`FAILED` are deliberately absent — they're SSE progress events only and never written to `Invoice.status`.
  - **`verification_accuracy`** reads `sa_alerts`, not the current status: denominator is invoices that reached a verification decision (`VERIFIED`/`NEEDS_REVIEW`/`SENT`/`PAID`), numerator is those with no alerts. `status` is mutable, so an invoice corrected out of `NEEDS_REVIEW` and sent would otherwise score as a clean first pass. `UPLOADED` rows are excluded rather than counted as failures — they haven't been judged yet.
  - **`revenue_over_time`** added as the mirror of inbound's `spend_over_time`; not in the field list above, but the FE grid mirrors `MetricsGrid.tsx`'s layout, which includes a trend panel.
- [x] **Task 8.1.5 (tests) — done 2026-07-29.** `tests/test_outbound_dashboard.py`, 14 tests, mirroring `test_dashboard.py`'s fixtures (in-memory SQLite + `StaticPool`, `MOCK_TENANT_ID`, per-file self-contained since `tests/` has no `conftest.py`). Covers aggregate correctness, tenant isolation, **direction isolation** (an `INBOUND` row for the same tenant must not be reported as a receivable — the failure mode this whole feature exists to prevent), `average_days_to_payment` counting only rows where both `sent_at` and `paid_at` exist, the overdue boundary (due yesterday counts, due today/future and null `due_date` don't), `PAID`-past-due excluded from at-risk, filter narrowing, and absence of any combined/net field in the response.
- [x] **Task 8.1.3:** Done 2026-07-29 as part of Feature 2.1's build — `routers/outbound_invoices.py::confirm_send_outbound_invoice()` stamps `sent_at` (`VERIFIED`/`NEEDS_REVIEW` → `SENT`), and `mark_outbound_invoice_paid()` (a new endpoint written into `feature_2.1_vendor_flow_ingestion.md`'s scope since Mark Paid wasn't concretely speced anywhere until this pass) stamps `paid_at` (`SENT` → `PAID`). Both tested in `tests/test_outbound_ingestion.py`.
- [x] **Task 8.1.4 (list-endpoint half only) — done 2026-07-29, bundled into Feature 7.1's build.** `routers/outbound_dashboard.py::list_outbound_invoices()` — `GET /outbound-dashboard/invoices`, pagination/filter logic (`customer_name`/`start_date`/`end_date`/`status`/`status_in`), zero edits to `routers/invoices.py`. Built here (not by Dev 2) since Feature 7.1's Task 7.1.4 (overdue computation) needed a real list query to attach to immediately. **Still open**: `get_outbound_dashboard_metrics()` (the aggregate-metrics endpoint feeding `OutboundMetricsGrid.tsx`) is a separate function in this same router file, not built yet — that's still Dev 2's remaining work for this feature.

### Verification Plan
* **Manual Verification:**
  - Receive-only tenant: confirm Dashboard is pixel-identical to today's, no new UI elements.
  - Send-only tenant: confirm only outbound metrics render, no empty inbound half.
  - Both active: confirm both halves render simultaneously with correct, independent data; confirm no combined/net figure appears anywhere on the page.
  - Mark an outbound invoice `PAID`; confirm `average_days_to_payment` reflects the real `paid_at - sent_at` elapsed time, not a placeholder.
  - `GET /outbound-dashboard/invoices`: confirm it paginates correctly via `X-Total-Count`, `customer_name` narrows to one customer, and `routers/invoices.py`'s existing `GET /invoices` behavior is completely unaffected (regression check — same file, zero edits).
