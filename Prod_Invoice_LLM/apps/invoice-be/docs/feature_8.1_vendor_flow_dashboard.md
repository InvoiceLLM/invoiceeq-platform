# Feature 8.1: Service Flow — Outbound Dashboard

Extends [feature_8_dashboard.md](feature_8_dashboard.md). Spec only — no implementation yet, pending approval of the full Service Flow document set.

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
- [ ] **Task 8.1.1:** Add `sent_at`, `paid_at` columns to `Invoice` (Alembic migration, additive).
- [ ] **Task 8.1.2:** Build `routers/outbound_dashboard.py::get_outbound_dashboard_metrics()`.
- [ ] **Task 8.1.3:** Wire `sent_at`/`paid_at` writes into the confirm-send and mark-paid endpoints (`feature_2.1`/`feature_7.1`).
- [ ] **Task 8.1.4:** Build `routers/outbound_dashboard.py::list_outbound_invoices()` — `GET /outbound-dashboard/invoices`, own pagination/filter logic (`customer_name`/`start_date`/`end_date`/`status`), zero edits to `routers/invoices.py`. Feeds `invoice-fe`'s outbound Auditor tab (see `feature_4.1_vendor_flow_auditor.md`, FE), not Dashboard.

### Verification Plan
* **Manual Verification:**
  - Receive-only tenant: confirm Dashboard is pixel-identical to today's, no new UI elements.
  - Send-only tenant: confirm only outbound metrics render, no empty inbound half.
  - Both active: confirm both halves render simultaneously with correct, independent data; confirm no combined/net figure appears anywhere on the page.
  - Mark an outbound invoice `PAID`; confirm `average_days_to_payment` reflects the real `paid_at - sent_at` elapsed time, not a placeholder.
  - `GET /outbound-dashboard/invoices`: confirm it paginates correctly via `X-Total-Count`, `customer_name` narrows to one customer, and `routers/invoices.py`'s existing `GET /invoices` behavior is completely unaffected (regression check — same file, zero edits).
