# Feature 8: Email Ingest & Outbound Delivery Settings

Settings page for a tenant to manage both inbound email ingestion and outbound invoice delivery configurations.

### Navigation
Lives under the **Settings** sidebar tab as a sub-section (`Settings → Email`), alongside Connectors (`feature_7_connectors.md`) and Webhooks (`feature_9_webhooks.md`).

### Theme & Styling Specifications
* Alias display card: `bg-[#151B26] border border-[#222D3D] rounded-xl p-4`, monospace alias text with a copy-to-clipboard button.
* Allowed-senders list: same row style as `feature_7_connectors.md`'s connector cards.
* Outbound Configuration: Text input for *Outbound Sender Email*, with a verify indicator and instructions for domain validation.

### File Coordinates
* Settings Page: [apps/invoice-fe/app/settings/email/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/settings/email/page.tsx) *(not yet created)*
* Allowed-Senders Manager: [apps/invoice-fe/components/settings/EmailSendersList.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/settings/EmailSendersList.tsx)
* Outbound Configuration Component: [apps/invoice-fe/components/settings/OutboundEmailSettings.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/settings/OutboundEmailSettings.tsx) *(not yet created)*

### Tasks
- [ ] **Task 8.1: Display Inbound Alias & Manage Senders**
  - Fetch and show the tenant's inbound alias with copy action.
  - List/add/remove allowed sender addresses via `/api/v1/settings/email-senders`.
- [ ] **Task 8.2: Outbound Sender Email Configuration**
  - Input field to save/update `outbound_sender_email` via `PUT /settings/vendor-flow`.
  - Format-validate input client-side before dispatching save request.

### Verification Plan
* **Manual Verification**: Verify copy alias works. Add/remove a sender and verify DB updates. Save a valid outbound sender email and confirm settings reload persistence.

