# Feature 8: Email Setup (Inbound & Outbound Authorized Sets)

Settings page for a tenant to manage authorized email sets for the **one global** app mailbox.

### Product model (2026-08-10)
* **App mailbox (platform-wide, not per tenant):** `invoices@invoiceeq.app` — every tenant sends to and receives notifications from this same address.
* **Inbound set / Outbound set:** tenant-owned emails; webhook resolves **tenant + direction** from `From`, not from `To`.
* Authorized `email` is **globally unique** (one address → one workspace).

### Navigation
**Settings → Email** (`/settings/email`).

### File Coordinates
* `app/settings/email/page.tsx` — mailbox copy + two set lists
* `components/settings/EmailSendersList.tsx` — `emailSet: "inbound" | "outbound"`
* Proxies: `app/api/email/settings/email-senders/*`, `app/api/email/settings/mailbox/route.ts`

### Tasks
- [x] **Task 8.1:** Display global mailbox with copy (`GET /email/settings/mailbox`).
- [x] **Task 8.2–8.3:** Inbound / outbound authorized email CRUD.
- [x] **Task 8.4:** Dual-set redesign; Gap 147 superseded.
- [x] **Task 8.5:** Global mailbox (not `{tenant_id}@…`).
