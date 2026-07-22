# Feature 8: Email Ingestion Settings

Settings page for a tenant to find their inbound email alias and manage
which sender addresses are allowed to submit invoices by email.

### Theme & Styling Specifications
* Alias display card: `bg-[#151B26] border border-[#222D3D] rounded-xl p-4`,
  monospace alias text with a copy-to-clipboard button.
* Allowed-senders list: same row style as `feature_7_connectors.md`'s
  connector cards for visual consistency within Settings.

### File Coordinates
* Settings Page: [apps/invoice-fe/app/settings/email-ingestion/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/settings/email-ingestion/page.tsx) *(not yet created)*
* Allowed-Senders Manager: [apps/invoice-fe/components/settings/EmailSendersList.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/settings/EmailSendersList.tsx) *(not yet created)*
* Proxy Routes: none exist yet under `app/api/settings/email-senders/`. Backend endpoints are spec'd in `be_features/feature_14_email_ingestion.md` Task 14.3 — not yet built.

### Tasks
- [ ] **Task 8.1: Display Inbound Alias**
  - Fetch and show the tenant's fixed inbound alias (`GET /api/v1/settings/email-alias` — or read off the tenant context if already available client-side).
  - Copy-to-clipboard action.
- [ ] **Task 8.2: Manage Allowed Senders**
  - List/add/remove allowed sender addresses via `/api/v1/settings/email-senders`.
  - Inline validation (basic email format) before submit.

### Verification Plan
* **Manual Verification**: open the settings page, copy the alias, add a
  sender, confirm it round-trips through the backend list.
