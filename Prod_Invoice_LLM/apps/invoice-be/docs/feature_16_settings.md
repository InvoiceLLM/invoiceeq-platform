# Feature 16: Settings

**Implemented 2026-07-28.** First time "Settings" exists as a formal BE feature — there was no `feature_*_settings.md` before this. Consolidates, by reference only (no content duplication), what already conceptually belongs under a Settings screen — [feature_9_connectors.md](feature_9_connectors.md), [feature_14_email_ingestion.md](feature_14_email_ingestion.md), [feature_15_webhooks.md](feature_15_webhooks.md) — plus the two new Service Flow toggles.

### File Coordinates
* Router: [apps/invoice-be/routers/settings.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/settings.py) → `get_vendor_flow_settings()` (`GET /settings/vendor-flow`), `update_vendor_flow_settings()` (`PUT /settings/vendor-flow`).
* Model: `apps/invoice-be/models.py::Tenant` — the three additive columns below (migration `e1f2a3b4c5d6`).
* Existing, unmodified: `apps/invoice-be/dependencies.py::get_tenant_context()` — read from, not edited, to get the current user's role for the Admin-only check.
* Tests: `apps/invoice-be/tests/test_settings.py` — 7/7 passing.

### Functionality

**Toggles:** `Tenant.receive_invoices_enabled: bool` (default `True` — preserves current behavior) and `Tenant.send_invoices_enabled: bool` (default `False` — new capability, opt-in).

**Outbound sender email:** `Tenant.outbound_sender_email: str | None` (default `None`) — the "from" address used when sending verified outbound invoices via email.

**Validation rules on `PUT /settings/vendor-flow`**:
1. Rejects `send_invoices_enabled=True` if `outbound_sender_email` is null (`400 Bad Request`).
2. Rejects `send_invoices_enabled=True` if `Tenant.billing_plan` is not `'pro_combined'` (`402 Payment Required`). This ensures the tenant is subscribed to the Combined Pro tier (₹8,999/month) before activating outbound flows.
3. Turning `send_invoices_enabled` off does not clear `outbound_sender_email` or downgrade the billing plan automatically.

**Admin-only enforcement:** `PUT /settings/vendor-flow` checks the requesting user's `role == "Admin"` (via the existing, unmodified `get_tenant_context()`); Auditor/Viewer roles get `403`. `GET /settings/vendor-flow` is readable by any authenticated role, since the FE needs it just to decide which tabs to render, not to change anything.

**Signup-time interaction:** whatever the signup flow currently asks (if anything) about inbound/outbound only sets these two columns' *initial* values — Settings is the permanent, ongoing control from that point forward.

**What these toggles actually gate** (for cross-reference, not re-specified here):
- Ingestion: the *Send Invoices* tab ([feature_3.1_vendor_flow_ingestion.md](feature_3.1_vendor_flow_ingestion.md) FE) only renders if `send_invoices_enabled`.
- Dashboard: single-view vs. split-screen behavior ([feature_8.1](feature_8.1_vendor_flow_dashboard.md)) is entirely driven by the combination of both flags.
- Auditor: the outbound alert tab ([feature_7.1](feature_7.1_vendor_flow_auditor.md)) follows the same rule as Ingestion.
- Chat ([feature_6.1](feature_6.1_vendor_flow_chat.md)): no explicit gate needed — if `send_invoices_enabled` is `False`, there's simply no outbound data for the SQL/RAG routes to find, so it degrades naturally without any special-case code.

### Explicitly out of scope
- Connectors/Email Ingestion/Webhooks implementation — those remain their own features, referenced here only because they'll eventually live on the same screen; no change to their specs or status.
- Any UI — covered in the FE counterpart, [feature_10_settings.md](feature_10_settings.md).

### Tasks
- [x] **Task 16.1:** Add `receive_invoices_enabled`, `send_invoices_enabled`, `outbound_sender_email` columns to `Tenant` (Alembic migration `e1f2a3b4c5d6`, additive, matching defaults above).
- [x] **Task 16.2:** Build `routers/settings.py` — `GET`/`PUT /settings/vendor-flow`, Admin-only enforcement on the `PUT`, `outbound_sender_email` format validation + the "can't enable send without a sender email" rule.

### Verification Plan
* **Manual Verification:**
  - Confirm every existing tenant row, post-migration, has `receive_invoices_enabled=True`, `send_invoices_enabled=False`, `outbound_sender_email=NULL` — no behavior change for any current tenant.
  - As an Auditor-role user, attempt `PUT /settings/vendor-flow`; confirm `403`.
  - As an Admin, attempt to turn `send_invoices_enabled` on with no `outbound_sender_email` set; confirm `400`.
  - As an Admin, set `outbound_sender_email` then toggle `send_invoices_enabled` on; confirm `GET /settings/vendor-flow` reflects both immediately.
