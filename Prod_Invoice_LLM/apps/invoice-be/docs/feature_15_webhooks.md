# Feature 15: Outbound Webhooks

Let a tenant register an HTTP endpoint to receive real-time notifications when an invoice's status changes (supporting both Inbound and Outbound flows) instead of polling the API.

**Built 2026-07-29.** All 5 tasks complete; 14 new tests (`tests/test_webhooks.py`) plus live verification against the real API (SSRF rejection and valid creation both confirmed against the real local Postgres, not just mocks). Full suite 138/138 passing.

### File Coordinates
* Model: `apps/invoice-be/models.py` → `WebhookSubscription`: `tenant_id`, `target_url`, `secret`, `subscribed_events` (list), `enabled`, `consecutive_failures`. Migration `d2e3f4a5b6c7`.
* Dispatch helper: `apps/invoice-be/services/webhooks.py` → `dispatch_webhook_event(db_session, tenant_id, event_type, payload)`, `validate_webhook_target_url()` (SSRF guard), `_deliver_with_retry()`, `_sign_payload()`.
* Router: `apps/invoice-be/routers/webhooks.py` → `GET/POST/PUT/DELETE /api/v1/webhooks`.
* Hook points (**corrected from the original spec below** — the actual SENT/PAID transitions live in `routers/outbound_invoices.py`, not `outbound_handlers.py`/`outbound_audit.py`):
  * Inbound status changes (`queue_worker/handlers.py::handle_process_invoice`, right after the commit that sets `status`) → fires `invoice.completed` or `invoice.audit_required`.
  * Inbound audit finalization (`routers/audit.py::resolve_audit_invoice`, only when `target_status` was actually applied) → fires `invoice.paid` or `invoice.rejected`.
  * Outbound status changes (`routers/outbound_invoices.py::confirm_send_outbound_invoice` / `mark_outbound_invoice_paid`, via a shared `_dispatch_outbound_webhook()` helper) → fires `outbound_invoice.sent` or `outbound_invoice.paid`.
  * **`outbound_invoice.overdue` is not fired anywhere** — overdue is a virtual, read-time-only computation (Feature 7.1/8.1), not a real status transition, so there's no single moment to fire it from without a new scheduled job. Deliberately deferred, same as this codebase's existing OVERDUE-status deferrals elsewhere — event type still accepted on subscription (validated against `ALLOWED_EVENT_TYPES`) so a tenant can pre-register for it before the poller exists.

### Functionality (target design)
`WebhookSubscription` rows are tenant-scoped: `target_url`, a per-subscription `secret` (used for HMAC-SHA256 signing, never returned by the API after creation), and `subscribed_events` (subset of: `invoice.completed`, `invoice.audit_required`, `invoice.paid`, `invoice.rejected`, `outbound_invoice.sent`, `outbound_invoice.overdue`, `outbound_invoice.paid`). All hook points call `dispatch_webhook_event(tenant_id, event_type, payload)` right after their database commit.
duplicated logic at each call site. Delivery: POST the event payload with
an `X-Webhook-Signature` header (HMAC-SHA256 of the raw body using the
subscription's `secret`), 3 retries with exponential backoff on
non-2xx/timeout, and auto-disable (`enabled = False`) a subscription after
10 consecutive failures — surfaced in the settings UI so the tenant
notices instead of silently losing events forever.

**Security**: `target_url` is validated against SSRF at creation time —
reject URLs resolving to private/link-local/loopback IP ranges (a tenant
could otherwise point a webhook at internal infrastructure). Delivery
requests use a short timeout and don't follow redirects to an
unvalidated host.

### Tasks
- [x] **Task 15.1: `WebhookSubscription` model + migration** — `d2e3f4a5b6c7`, applied cleanly against real local Postgres.
- [x] **Task 15.2: Subscription CRUD endpoints** — `GET/POST/PUT/DELETE /api/v1/webhooks`. `target_url` SSRF-validated on create and on update (only when `target_url` is actually being changed). `secret` generated server-side (`secrets.token_hex(32)`), returned only in the `POST` response, never on subsequent `GET`/`PUT`.
- [x] **Task 15.3: `dispatch_webhook_event()` + HMAC signing + retry/backoff** — `X-Webhook-Signature` (HMAC-SHA256), 3 attempts with exponential backoff (1s, 2s) on non-2xx/timeout, no redirect-follow on delivery (a validated hostname must not be able to silently hop to an unvalidated one at delivery time via a redirect).
- [x] **Task 15.4: Wire into the real hook points** — see File Coordinates above (locations corrected from this doc's original spec). Every dispatch call is wrapped in its own try/except — a webhook delivery failure never fails the invoice operation that triggered it.
- [x] **Task 15.5: Auto-disable after 10 consecutive failures + re-enable** — `consecutive_failures` resets to 0 on any successful delivery; hits `enabled=False` at the threshold. Re-enabling via `PUT .../{id}` with `enabled: true` also resets the counter to 0, giving the subscription a clean slate instead of immediately re-tripping on the next delivery with a stale count.

### Verification Plan
* **Automated Tests** (`tests/test_webhooks.py`, 14/14 passing): SSRF rejection (loopback, private, link-local/cloud-metadata, bad scheme), valid public host accepted, unknown event-type rejection, secret returned once and never leaked on list, tenant isolation on update/delete, HMAC signature correctness, event-type filtering (a subscription only fires for events it subscribed to), retry-then-succeed (mocked timeout + 500 + 200), auto-disable at the exact threshold, disabled subscriptions skipped entirely.
* **Live verification (2026-07-29)**: against the real API + real local Postgres (not just SQLite/mocks) — confirmed a loopback `target_url` is rejected with a real 400, a valid creation succeeds with a real generated secret, and the secret never appears on a subsequent `GET`.
* **Not yet done**: an actual end-to-end delivery to a real external receiver (blocked by this session's own auto-mode safety classifier, which correctly flagged posting to an unfamiliar external test service as an unnecessary outbound call) — the retry/signature/auto-disable behavior is verified via mocked HTTP instead, which is the same approach this codebase already uses elsewhere for outbound calls (e.g. `test_outbound_ingestion.py` mocking blob storage/queue).
