# Feature 16: Settings

New feature — this is the first time "Settings" exists as a formal BE feature. No `feature_*_settings.md` existed before this; there's also no live `/settings` route on the frontend yet (confirmed by listing `apps/invoice-fe/app/**/page.tsx`). Consolidates, by reference only (no content duplication), what already conceptually belongs under a Settings screen — [feature_9_connectors.md](feature_9_connectors.md), [feature_14_email_ingestion.md](feature_14_email_ingestion.md), [feature_15_webhooks.md](feature_15_webhooks.md) — plus the two new Vendor Flow toggles.

### File Coordinates (planned)
* New router: `apps/invoice-be/routers/settings.py` — `GET /settings/vendor-flow`, `PUT /settings/vendor-flow`.
* Model: `apps/invoice-be/models.py::Tenant` — two new additive columns.
* Existing, unmodified: `apps/invoice-be/dependencies.py::get_tenant_context()` — read from, not edited, to get the current user's role for the Admin-only check.

### Functionality

**Toggles:** `Tenant.receive_invoices_enabled: bool` (default `True` — every existing tenant already uses this flow, so the default preserves current behavior exactly) and `Tenant.send_invoices_enabled: bool` (default `False` — new capability, opt-in).

**Outbound sender email:** `Tenant.outbound_sender_email: str | None` (default `None`) — the "from" address used when a confirmed outbound invoice ([feature_2.1](feature_2.1_vendor_flow_ingestion.md)'s `SENT` step) is actually emailed to the customer. This resolves that feature's previously-open "delivery mechanism not yet decided" question: it's email, reusing the same ACS Email connection [feature_14_email_ingestion.md](feature_14_email_ingestion.md) already brings into the project, just configured for sending instead of receiving. Format-validated on save (not verified against ACS at save time — actual send-time failures surface as an alert on the invoice, same pattern as any other outbound alert).

**Validation rule:** `PUT /settings/vendor-flow` rejects `send_invoices_enabled=True` if `outbound_sender_email` is null (`400`) — you can't turn on sending with nowhere to send from. Turning `send_invoices_enabled` off does not clear `outbound_sender_email`, so re-enabling later doesn't require re-entering it.

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
- [ ] **Task 16.1:** Add `receive_invoices_enabled`, `send_invoices_enabled`, `outbound_sender_email` columns to `Tenant` (Alembic migration, additive, matching defaults above).
- [ ] **Task 16.2:** Build `routers/settings.py` — `GET`/`PUT /settings/vendor-flow`, Admin-only enforcement on the `PUT`, `outbound_sender_email` format validation + the "can't enable send without a sender email" rule.

### Verification Plan
* **Manual Verification:**
  - Confirm every existing tenant row, post-migration, has `receive_invoices_enabled=True`, `send_invoices_enabled=False`, `outbound_sender_email=NULL` — no behavior change for any current tenant.
  - As an Auditor-role user, attempt `PUT /settings/vendor-flow`; confirm `403`.
  - As an Admin, attempt to turn `send_invoices_enabled` on with no `outbound_sender_email` set; confirm `400`.
  - As an Admin, set `outbound_sender_email` then toggle `send_invoices_enabled` on; confirm `GET /settings/vendor-flow` reflects both immediately.
