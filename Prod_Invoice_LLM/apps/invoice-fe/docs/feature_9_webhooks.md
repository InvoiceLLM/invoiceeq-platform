# Feature 9: Webhooks Settings

Settings page to add/edit webhook endpoints, pick which events they
receive, and see recent delivery status.

### Navigation
Lives under the **Settings** sidebar tab as a sub-section (`Settings → Webhooks`), alongside Connectors (`feature_7_connectors.md`) and Email Ingestion (`feature_8_email_ingestion.md`) — the sidebar exposes one "Settings" entry, and these three features are its sub-pages.

### Theme & Styling Specifications
* Subscription rows: same list style as `feature_8_email_ingestion.md`'s
  allowed-senders list, for visual consistency within Settings.
* Delivery-status badge: Healthy `bg-[#10B981]/15 text-[#10B981]`,
  Disabled (auto-disabled after failures) `bg-red-500/15 text-red-400`.

### File Coordinates
* Settings Page: [apps/invoice-fe/app/settings/webhooks/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/settings/webhooks/page.tsx) — `WebhooksPage` holds the whole screen (list + modal) in one client component; no separate list component was ever split out. Functions: `fetchWebhooks`, `openCreateModal`, `openEditModal`, `closeModal`, `handleSubmitWebhook`, `handleToggleWebhook`, `handleDeleteWebhook`, `handleCopySecret`, `handleCopyUrl`, `toggleEventSelection`, `loadDeliveries`, `handleToggleDeliveries` (last two added by Gap 194), `errorMessage` (module-level). Types: `WebhookSub` (now carries `event_failure_counts`), `WebhookDelivery`.
* Subscription Form/List: *not built as a separate `components/settings/WebhookSubscriptionList.tsx` — the list and form live inline in the page above.*
* Proxy Routes: [app/api/webhooks/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/webhooks/route.ts) (`GET`, `POST`), [app/api/webhooks/[id]/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/webhooks/%5Bid%5D/route.ts) (`PUT`, `DELETE`) and [app/api/webhooks/[id]/deliveries/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/webhooks/%5Bid%5D/deliveries/route.ts) (`GET`, added by Gap 194), all thin `proxyJson` passthroughs to the backend `routers/webhooks.py`.

### Tasks
- [x] **Task 9.1: Add/Edit Webhook Endpoint**
  - Form: target URL, event checkboxes (Inbound: `invoice.completed`, `invoice.audit_required`, `invoice.paid`, `invoice.rejected` / Outbound: `outbound_invoice.sent`, `outbound_invoice.overdue`, `outbound_invoice.paid`).
  - Secret shown once at creation only (matches backend never returning it again).
  - **Built as one modal serving both modes** (edit half added 2026-08-12, tracker Gap 203 — create had shipped earlier). `editingId` state selects the mode: `null` → `POST /api/webhooks`, a webhook id → `PUT /api/webhooks/{id}`. `openEditModal(sub)` prefills `targetUrl`/`selectedEvents` from the row and clears `createdSecret`, so an edit always shows the form and never the (unavailable) secret panel; `closeModal()` resets `editingId` and the fields on every exit so create can't inherit edited values. The edit request sends only `target_url` + `subscribed_events` — `enabled` is left out on purpose so saving an edit can't re-enable an auto-disabled endpoint or reset `consecutive_failures`, which stay owned by the Power toggle (`handleToggleWebhook`, the only caller that sends `enabled`). The PUT response (public dict, no secret) is merged over the row in place rather than triggering a refetch.
- [~] **Task 9.2: Subscription List + Status**
  - Show Healthy/Disabled state per subscription; manual re-enable action for a Disabled one.
  - **Built, but not as the badge this doc's Theme section describes.** Enabled/disabled is carried by the Power button's own colour (emerald when enabled, slate when not) plus its title text, and that same button is the manual re-enable action (`handleToggleWebhook` — the only caller that sends `enabled`). No separate `bg-[#10B981]/15` / `bg-red-500/15` status badge was ever added; the Theme spec above is aspirational on that point.
  - **Delivery history added 2026-08-12 (tracker Gap 194).** A History button per row toggles an inline panel (`handleToggleDeliveries` → `loadDeliveries`, `GET /api/webhooks/{id}/deliveries?limit=25`). Fetched lazily on first open and cached per subscription id in `deliveries`, with an explicit Refresh so the panel can be re-checked after a fix without a page reload; `expandedId` keeps one panel open at a time. Each row shows event type, timestamp, attempt count, duration, the HTTP status (green for a 2xx, red otherwise) and the error string for a failure. Loading/empty/error states are all distinct, and the error path reuses the page's existing `errorMessage()` guard so a non-JSON response (HTML error page, gateway timeout) can never render its raw body into the UI. Deleting a webhook drops its cached history and collapses the panel.
  - **Health warning rewritten for Gap 194's backend semantics.** The old copy ("failed N consecutive times. Auto-disables at 10 failures") was no longer true: failures are counted per event type on the backend and the endpoint is auto-disabled only once an event type hits 10 *and* no other event type is still delivering. The warning now says that, and lists the failing events from `event_failure_counts` (`invoice.completed: 3 · outbound_invoice.overdue: 9`) so the tenant can see *which* event is broken rather than just that the endpoint is unhealthy.

### Verification Plan
* **Manual Verification**: add an endpoint, toggle event types, confirm
  the disabled state appears after simulating delivery failures.
* **Gap 194 (2026-08-12)**: `npx tsc --noEmit` clean. **Not verified**: no Playwright/live run — there is still no webhook e2e spec, and the screen is Admin-gated behind a real Clerk session; the delivery panel's fetch/render path was traced statically against the backend response shape asserted in `invoice-be/tests/test_webhooks.py::test_list_deliveries_returns_newest_first`.
