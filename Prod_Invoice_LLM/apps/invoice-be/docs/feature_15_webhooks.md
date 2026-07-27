# Feature 15: Outbound Webhooks

Let a tenant register an HTTP endpoint to receive real-time notifications
when an invoice's status changes, instead of polling the API.

### File Coordinates
* New model: `apps/invoice-be/models.py` → `WebhookSubscription` *(not yet created)*: `tenant_id`, `target_url`, `secret`, `subscribed_events` (list)
* New dispatch helper: `apps/invoice-be/services/webhooks.py` → `dispatch_webhook_event(tenant_id, event_type, payload)` *(not yet created)*
* New router: `apps/invoice-be/routers/webhooks.py` → `GET/POST/PUT/DELETE /api/v1/webhooks` *(not yet created)*
* Hook points (existing, real status-change sites — reused, not duplicated):
  [apps/invoice-be/queue_worker/handlers.py:275](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/queue_worker/handlers.py) `invoice.status = status` → fires `invoice.completed` or `invoice.audit_required`;
  [apps/invoice-be/routers/audit.py:68](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/audit.py) `invoice.status = target_status` → fires `invoice.paid` or `invoice.rejected` (corrected from the original `invoice.approved` — no `APPROVED` status exists; the only two manual-override targets `AuditResolutionPayload` accepts are `PAID`/`REJECTED`).

### Functionality (target design)
`WebhookSubscription` rows are tenant-scoped: `target_url`, a per-subscription
`secret` (used for HMAC-SHA256 signing, never returned by the API after
creation), and `subscribed_events` (subset of `invoice.completed`,
`invoice.audit_required`, `invoice.paid`, `invoice.rejected`). Both hook
points above call `dispatch_webhook_event(tenant_id, event_type, payload)`
right after their existing `session.commit()` — one shared helper, not
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
- [ ] **Task 15.1: `WebhookSubscription` model + migration**
- [ ] **Task 15.2: Subscription CRUD endpoints** — `GET/POST/PUT/DELETE /api/v1/webhooks`, target_url SSRF validation on create/update.
- [ ] **Task 15.3: `dispatch_webhook_event()` + HMAC signing + retry/backoff**
- [ ] **Task 15.4: Wire into the two existing hook points** — `queue_worker/handlers.py`, `routers/audit.py`, no duplicated dispatch logic.
- [ ] **Task 15.5: Auto-disable after 10 consecutive failures + re-enable endpoint**

### Verification Plan
* **Automated Tests**: SSRF rejection on private-IP `target_url`, HMAC
  signature correctness, retry/backoff behavior on a mock 500 endpoint,
  auto-disable after threshold, event-type filtering (a subscription only
  fires for events it subscribed to).
* **Manual Verification**: register a webhook against a local test
  receiver, move a test invoice through COMPLETED and PAID, confirm both
  deliveries arrive with valid signatures.
