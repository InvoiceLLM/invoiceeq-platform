# Feature 7: Audit Resolution & Finalization

Enable human auditor overrides, update database transaction states, and save template learning rules.

### File Coordinates
* Router: [apps/invoice-be/routers/audit.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/audit.py)

### Tasks
- [ ] **Task 7.1: Code Audit Resolution Endpoint**
  - Implement `PUT /api/v1/audit/resolve/{invoice_id}` endpoint.
  - Enable auditors to **dismiss** warnings (remove objects from the `sa_alerts` array column).
  - Update invoice status to final states: `PAID` or `REJECTED`.
  - *Note*: Form inputs are read-only in the UI; backend does not need to handle arbitrary metadata modifications.
- [ ] **Task 7.2: Implement Audit Logging**
  - Log audit details to `audit_logs` table (capture actor details, action taken, and timestamps).

### Verification Plan
* **Automated Tests**: Run `uv run pytest tests/test_audit.py` testing resolution overrides and status updates.
* **Manual Verification**: Correct a mock invoice in the Auditor UI tab, click Approve, and verify that the alerts are removed and status changes in the database.
