# Email domain migration runbook — inbound/outbound address rename

Founder-directed change, decided 2026-08-26. Not started — this is the plan, execution
pending GoDaddy/SendGrid access.

## Current state (live today)

- **Send-to (PDF ingestion):** not yet correctly live — bicep currently declares
  `invoices@outbound.invoicellm.admsofttech.com` for `EMAIL_APP_ADDRESS`, which is wrong
  (SendGrid Inbound Parse is registered against `inbound.invoicellm.admsofttech.com`, not
  `outbound.`, so mail sent to the bicep-declared address would never reach the app).
- **Live container's actual `EMAIL_APP_ADDRESS`:** `invoice@admsofttech.com` (also wrong —
  doesn't match Inbound Parse's registered hostname either).
- **Notification-from:** `invoices@outbound.invoicellm.admsofttech.com` (this one is correct
  and SendGrid-domain-authenticated today).
- **Inbound Parse registered hostname:** `inbound.invoicellm.admsofttech.com` → webhook
  `https://invoicellm.admsofttech.com/api/v1/email/mailintegration?key=<INBOUND_PARSE_SHARED_SECRET>`.

## Target state

| Purpose | Address |
|---|---|
| Send-to (end users email PDFs here) | `invoice@receive.invoicellm.admsofttech.com` |
| Notification-from (after extraction) | `invoice@notify.invoicellm.admsofttech.com` |

## Constraints found during design

- The bare domain `invoicellm.admsofttech.com` already has a CNAME pointing to the live web
  app (`invoiceeq-fd-endpoint.azurefd.net`) — DNS does not allow an MX record to coexist with
  a CNAME at the same exact hostname, so neither address can use the bare domain. Both must
  use a subdomain.
- `admsofttech.com` (no subdomain) already has a real company mail server
  (`mail.parktons.com`) handling real staff mailboxes (`admin@`, `sbanerji@`) — do not point
  its MX at SendGrid, that would break real company email.
- The shared inbound-parse secret (`INBOUND_PARSE_SHARED_SECRET` / Key Vault
  `SENDGRID-INBOUND-SECRET`) does not need to change — it authenticates the webhook
  regardless of which hostname triggered it.
- Sending two different "From" addresses by direction (inbound vs. outbound producing
  different notification senders) is a **future** code change to `services/outbound_email.py`
  — today there is only one `SENDGRID_FROM_EMAIL` for all outgoing mail. This runbook covers
  renaming that one shared sender address, not splitting it by direction.

## Steps, in dependency order

| # | Area | Action | Detail / value |
|---|---|---|---|
| 1 | SendGrid | Start domain authentication for the new sending domain | Domain: `notify.invoicellm.admsofttech.com` |
| 2 | SendGrid | Record the 3 CNAME values SendGrid generates | Exact values only known once step 1 runs |
| 3 | GoDaddy DNS | Add the 3 CNAME records from step 2 | Under the `admsofttech.com` zone |
| 4 | GoDaddy DNS | Add MX record for the new receiving subdomain | `receive.invoicellm.admsofttech.com` → `mail.parktons.com`, priority `10` |
| 5 | SendGrid | Verify domain authentication for `notify.invoicellm.admsofttech.com` | After DNS propagates |
| 6 | SendGrid | Add new Inbound Parse entry | Hostname `receive.invoicellm.admsofttech.com` → URL `https://invoicellm.admsofttech.com/api/v1/email/mailintegration?key=<existing INBOUND_PARSE_SHARED_SECRET>` |
| 7 | Key Vault | No change | Existing `SENDGRID-API-KEY` / `SENDGRID-INBOUND-SECRET` reused as-is |
| 8 | Bicep — `Prod_Invoice_LLM/infra/params.dev.json` | Update 3 values | `emailAppDomain` → `receive.invoicellm.admsofttech.com`; `emailAppAddress` → `invoice@receive.invoicellm.admsofttech.com`; `sendgridFromEmail` → `invoice@notify.invoicellm.admsofttech.com` |
| 9 | Code / `Prod_Invoice_LLM/infra/modules/compute/invoice-be.bicep` | No change | Params already declared generically |
| 10 | Azure | Redeploy `ca-invoice-be-dev` | Same 4-rung verification standard as this repo's other real deploys |
| 11 | Verification | Send a real test PDF | To `invoice@receive.invoicellm.admsofttech.com` |
| 12 | Verification | Confirm notification sender | Should show `invoice@notify.invoicellm.admsofttech.com`, not spam-flagged |

## Cleanup — only after step 11/12 confirm the new setup actually works, never before

| # | Area | Delete | Why it's redundant |
|---|---|---|---|
| 13 | SendGrid | Inbound Parse entry for `inbound.invoicellm.admsofttech.com` | Fully replaced by step 6 |
| 14 | SendGrid | Domain Authentication entry for `outbound.invoicellm.admsofttech.com` | Fully replaced by step 5 |
| 15 | GoDaddy DNS | MX record for `inbound.invoicellm.admsofttech.com` | No longer receiving anything |
| 16 | GoDaddy DNS | 3 CNAME records for `outbound.invoicellm.admsofttech.com` domain auth | No longer sending from that domain |
| 17 | SendGrid | Single Sender entry `invoices@outbound.invoicellm.admsofttech.com` (already showing "failed") | Redundant even before this change — domain authentication already covered it |

## Flagged separately — pre-existing dead entries, unrelated to this change

Found in the live SendGrid dashboard 2026-08-26. Different domain entirely
(`infinevocloud.com`, not the product domain) — likely early setup attempts by the
teammates who built Gap 321. Not touched by this migration either way; delete only if
confirmed nothing else depends on them.

| Area | Entry | Status |
|---|---|---|
| SendGrid Domain Auth | `em0.infinevocloud.com` | failed |
| SendGrid Domain Auth | `em7554.infinevocloud.com` | pending |
| SendGrid Single Sender | `application@infinevocloud.com` | failed |
| SendGrid Link Branding | `url5527.infinevocloud.com` | failed |

## Execution boundary

Steps 1, 2, 5, 6 are executable via the SendGrid API using the key already in Key Vault —
pending explicit founder go-ahead, since these are real writes to a live external account.
Steps 3, 4, 15, 16 require GoDaddy access, which is not available in this environment —
someone with GoDaddy access must perform these. Steps 7-10 follow this repo's standard
infra-devops execution and verification pattern once 1-6 are confirmed working.
