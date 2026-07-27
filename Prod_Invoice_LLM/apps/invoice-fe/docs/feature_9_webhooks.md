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
* Settings Page: [apps/invoice-fe/app/settings/webhooks/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/settings/webhooks/page.tsx) *(not yet created)*
* Subscription Form/List: [apps/invoice-fe/components/settings/WebhookSubscriptionList.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/settings/WebhookSubscriptionList.tsx) *(not yet created)*
* Proxy Routes: none exist yet under `app/api/webhooks/`. Backend endpoints spec'd in `docs/feature_15_webhooks.md` Task 15.2 — not yet built.

### Tasks
- [ ] **Task 9.1: Add/Edit Webhook Endpoint**
  - Form: target URL, event checkboxes (`invoice.completed`, `invoice.audit_required`, `invoice.paid`, `invoice.rejected`).
  - Secret shown once at creation only (matches backend never returning it again).
- [ ] **Task 9.2: Subscription List + Status**
  - Show Healthy/Disabled state per subscription; manual re-enable action for a Disabled one.

### Verification Plan
* **Manual Verification**: add an endpoint, toggle event types, confirm
  the disabled state appears after simulating delivery failures.
