# Feature 16: Settings

**Implemented 2026-07-28.** First formal BE Settings feature. Consolidates by reference: [feature_9_connectors.md](feature_9_connectors.md), [feature_14_email_ingestion.md](feature_14_email_ingestion.md), [feature_15_webhooks.md](feature_15_webhooks.md), plus Service Flow toggles.

### File Coordinates
* Router: `routers/settings.py` — `GET`/`PUT /settings/vendor-flow`
* Model: `Tenant.receive_invoices_enabled`, `send_invoices_enabled`, `outbound_sender_email` (migration `e1f2a3b4c5d6`)
* Tests: `tests/test_settings.py`

### Functionality

**Toggles:** `receive_invoices_enabled` (default `True`), `send_invoices_enabled` (default `False`).

**Email setup (redesigned 2026-08-10):** authorized inbound/outbound emails live on `TenantEmailSender.email_set`, not on a single Settings string. See Feature 14 / FE Feature 8.

**`outbound_sender_email`:** legacy nullable column kept for Gap 125 customer-delivery Reply-To experiments; **not** required to enable Send Invoices and **not** edited on the Email Setup screen.

**Validation on `PUT /settings/vendor-flow`** (updated 2026-08-10):
1. Rejects `send_invoices_enabled=True` if the tenant has **zero** `TenantEmailSender` rows with `email_set='outbound'` (`400`).
2. Rejects `send_invoices_enabled=True` if `billing_plan != 'pro_combined'` (`402`).
3. Turning send off does not clear email-set rows or downgrade the plan.

**Admin-only:** `PUT` requires `role == Admin`; `GET` any authenticated role.

**What toggles gate:** Ingestion Send tab, Dashboard split, Auditor outbound tab — unchanged. Chat degrades naturally with no outbound data.

### Tasks
- [x] **Task 16.1–16.2:** Columns + vendor-flow endpoints (2026-07-28).
- [x] **Task 16.3 (2026-08-10):** Gate Send Invoices on outbound authorized-email set instead of `outbound_sender_email`.

### Verification Plan
* Admin enabling send with empty outbound set → `400`.
* Admin with ≥1 outbound-set email + `pro_combined` → enable succeeds.
