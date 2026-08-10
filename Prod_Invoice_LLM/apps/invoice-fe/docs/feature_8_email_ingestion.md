# Feature 8: Email Setup (Inbound & Outbound Authorized Sets)

Settings for the **global** app mailbox and dual authorized email sets.

### Product model (2026-08-10)
* **App mailbox (platform-wide):** from `GET /email/settings/mailbox` (e.g. `invoices@invoiceeq.app` / env override).
* **Inbound / outbound sets:** who may email PDFs in, and who may receive **staff** notifications. App **never** emails end customers.
* **Auditor multi-select (Gap 125):** review screens load that direction’s set so the auditor can choose notify recipients before Approve/Pay/Send/Reject.

### File Coordinates
* `app/settings/email/page.tsx`, `components/settings/EmailSendersList.tsx`
* Proxies: `app/api/email/settings/email-senders/*`, `mailbox/route.ts`
* **Live receive (Gap 124):** SendGrid posts to **invoice-website** `POST /api/v1/email/mailintegration` (public relay → BE). FE settings still talk to BE via `/api/email/*` Multi-Zone rewrite — different path prefix on purpose.

### Tasks
- [x] **8.1–8.5:** Mailbox + dual-set CRUD; Gap 147 superseded.
- [x] **8.6 / Gap 125 FE:** Notify multi-select on inbound + outbound review actions; help copy updated.
