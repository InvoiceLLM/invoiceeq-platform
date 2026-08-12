# Gap 194 — Webhooks reliability (async dispatch, failure scoping, delivery log)

- [x] Read current `services/webhooks.py`, `routers/webhooks.py`, queue-worker enqueue pattern, Gap 203's FE state
- [x] models.py: `WebhookDeliveryLog` table + `WebhookSubscription.event_failure_counts`
- [x] Alembic migration `b8c1d4e7f209` (extends head `a2b3c4d5e6f7`; 3 unmerged heads pre-exist from other in-flight changes)
- [x] services/webhooks.py: `dispatch_webhook_event()` → enqueue only; new `deliver_webhook_now()` + `record_delivery_result()` do HTTP + log + failure accounting
- [x] queue_worker/handlers.py: `handle_deliver_webhook()`; main_worker.py routes task `deliver_webhook`
- [x] routers/webhooks.py: `GET /webhooks/{id}/deliveries`; `event_failure_counts` in public dict; cleared on re-enable; logs deleted with subscription
- [x] FE: `app/api/webhooks/[id]/deliveries/route.ts` proxy + additive delivery-log panel and corrected health warning on the settings page (Gap 203's edit modal untouched)
- [x] Backend tests — `tests/test_webhooks.py` 27 passed; `tests/test_outbound_overdue.py` 17 passed
- [x] `npx tsc --noEmit` on invoice-fe — clean
- [x] Updated `feature_15_webhooks.md` (Task 15.7), `feature_9_webhooks.md` (Task 9.2), BE tracker Gap 194 `[x]`, FE tracker new Gap 194 `[x]`

Status: complete. Left uncommitted. Not verified: live queue-worker delivery (needs a deploy) and the migration against a real DB (branch has unmerged heads).
