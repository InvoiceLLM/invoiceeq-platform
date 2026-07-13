# Feature 7: Audit Resolution & Finalization

Enable human auditor overrides, update database transaction states, and save template learning rules.

### File Coordinates
* Router: [apps/invoice-be/routers/audit.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/audit.py) → `PUT /audit/resolve/{invoice_id}` → `resolve_audit_invoice()`

### Functionality
`resolve_audit_invoice()` validates `payload.status` is `PAID`/`REJECTED`, fetches the tenant-scoped `Invoice` row, then filters `invoice.sa_alerts` down to whatever wasn't named in `payload.dismissed_alerts` (matching by string, `id`, `type`, or `message` — alerts can be stored as either plain strings or dicts, so both shapes are handled). It writes the new status, inserts an `AuditLog` row (`action="RESOLVE_INVOICE"`, `details` = before/after alert lists) capturing `actor_user_id`/`actor_role` from the JWT context, and commits both in one transaction. Today this is the entire endpoint — no `corrections` payload, no `suggested_rule` response field; those are Tasks 7.3/7.4 below, not yet implemented.

### Tasks
- [ ] **Task 7.1: Code Audit Resolution Endpoint**
  - Implement `PUT /api/v1/audit/resolve/{invoice_id}` endpoint.
  - Enable auditors to **dismiss** warnings (remove objects from the `sa_alerts` array column).
  - Update invoice status to final states: `PAID` or `REJECTED`.
  - *Note*: superseded by Task 7.3 below — fields are no longer strictly read-only.
- [ ] **Task 7.2: Implement Audit Logging**
  - Log audit details to `audit_logs` table (capture actor details, action taken, and timestamps).
- [ ] **Task 7.3: Accept field corrections on resolve** *(new — closes the audit→trainer feedback loop)*
  - Extend `PUT /api/v1/audit/resolve/{invoice_id}` to accept an optional `corrections: dict[str, Any]` payload (field name → corrected value). Persist the corrected values onto the `Invoice` row.
  - Log the before/after diff in `audit_logs.details` (Task 7.2) — this is the raw training signal: what the AI got wrong and what a human said instead.
  - This requires the FE metadata inspector to become editable — see `fe_features/feature_4_auditor.md` Task 4.6.
- [ ] **Task 7.4: Detect correction patterns and suggest a trainer rule** *(new)*
  - After persisting a correction (Task 7.3), check whether the same field has been corrected on ≥N recent invoices — for this vendor (suggests a Vendor-scope rule) or across multiple vendors (suggests a Global-scope rule, per `feature_10_trainer.md`).
  - Return a `suggested_rule: {scope, field, sample_correction} | None` on the resolve response so the FE can surface "Want to save this as a rule?" inline (`feature_4_auditor.md` Task 4.7) instead of requiring a separate trip to the Trainer sandbox.
  - Threshold `N` and the lookback window should be configurable per tenant, not hardcoded — false-positive suggestions erode trust in the feature fast.

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_audit.py` testing resolution overrides and status updates.
* **Manual Verification**: Correct a mock invoice in the Auditor UI tab, click Approve, and verify that the alerts are removed and status changes in the database.
