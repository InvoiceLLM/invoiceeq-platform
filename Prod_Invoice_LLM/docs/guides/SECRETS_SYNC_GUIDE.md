# Azure Key Vault & GitHub Actions Secrets — How It Actually Works

> Last reconciled 2026-09-07 against `infra/05-secrets.bicep`, `infra/modules/compute/*.bicep`,
> `infra/params.dev.json`, `infra/params.dev.secrets.json.example`, `infra/deploy-all.ps1` and
> `Invoice_LLM/.github/workflows/*`. Bicep env/secret blocks are described from the committed
> state (`git show HEAD:…`); the working tree carries uncommitted Feature 29 phase-2 edits to
> those files (new `ENABLE_*` flags only, no new secrets).

## Correction (2026-08-01, re-checked 2026-09-07)

This document previously described an automated daily GitHub Actions
workflow (`sync-secrets.yml`) that synced secrets from Azure Key Vault to
GitHub Repository Secrets. **That workflow does not exist and never has.**
The workflows live at the repository root, `Invoice_LLM/.github/workflows/`
(one level above `Prod_Invoice_LLM/`), and as of 2026-09-07 are exactly:

| Workflow | Purpose | GitHub secret it reads |
|---|---|---|
| `deploy-dev.yml` | push to `master`/`develop` → build/push/deploy changed services to `rg-invoice-llm-dev` | `Azure_Dev_Credentials` |
| `deploy-prod.yml` | tag `v*` or manual dispatch → deploy to `invoice-llm-prod` under the `production` environment gate | `AZURE_CREDENTIALS_PROD` |
| `_deploy-service.yml` | reusable build + `az containerapp update` + health wait + auto-rollback | passed in as `azure_credentials` |
| `e2e-regression.yml` | manual only; local docker-compose stack + `pytest -m e2e` | `AZURE_CREDENTIALS` |

`build-desktop.yml` (Windows Tauri build) was added and deleted on
2026-08-30 and does not exist. The section below describes the process
that is actually in place.

## Overview

There is no automated secret synchronization between Azure Key Vault and
GitHub. Application secrets are seeded into Key Vault manually, once, via
the staged bicep deployment; CI never writes them. The one CI path that
touches Key Vault at all is `e2e-regression.yml`, which *reads*
`AZURE-OPENAI-API-KEY` and `AZURE-DOC-INTEL-KEY` from `kv-invoicellm-dev`
for an on-demand test run.

## How secrets actually flow

```
infra/params.dev.secrets.json (local, gitignored; copy from .example)
        │
        │  manually run once (or on rotation)
        ▼
Stage 5 (infra/05-secrets.bicep) via deploy-all.ps1 or a direct
`az deployment group create --template-file infra/05-secrets.bicep ...`
  - 8 values come from the secrets file
  - 5 (+4 optional) are COMPUTED inside the template with listKeys()/existing
    references to the Stage 3/4 resources (Postgres, Redis, Storage, OpenAI, DocIntel)
        │
        ▼
Azure Key Vault kv-invoicellm-dev  (name = kv-<namingPrefix>-<env>; params.dev.json
sets namingPrefix = "invoicellm" — NOT the "invoice-llm" that deploy-all.ps1 defaults to)
        │
        ▼
Container apps and jobs (08-apps.bicep → modules/compute/*.bicep, and the *-only.bicep
job templates) reference the secrets as Key Vault secret references resolved by the
user-assigned identity id-invoicellm-dev (Key Vault Secrets User, 07-rbac.bicep).
```

`deploy-dev.yml` / `deploy-prod.yml` never run bicep and never re-sync Key
Vault secrets; they only `az login`, `az acr login`, build, push and
`az containerapp update --image`. The single non-secret value they read
from the repo is `nextPublicClerkPublishableKey` in the committed
`infra/params.<env>.json` (a public browser-bundle value, baked into the
FE/website images as a Docker build-arg), plus `customDomainName` from the
same file.

## Secret Mapping (seeded into Key Vault by Stage 5, not GitHub)

Exactly what `05-secrets.bicep` declares. "Computed" secrets need no entry
in the secrets file.

| Azure Key Vault Secret | Source | Consumed by (container-app secret name) |
|------------------------|--------|------------------------------------------|
| `DATABASE-URL` | computed: `postgresql://<dbAdminLogin>:<dbAdminPassword>@<server FQDN>:5432/invoice_db?sslmode=require` (`dbAdminPassword` from the secrets file; skipped when `manageDatabaseUrlSecret=false`) | be, worker, every job (`db-url-secret`) |
| `REDIS-URL` | computed via `listKeys()` on the Redis Enterprise database: `rediss://:<key>@<host>:<port>/0` | be, worker, every job (`redis-url-secret`) |
| `AZURE-STORAGE-CONNECTION-STRING` | computed via `listKeys()` on the storage account | be, worker, every job (`storage-conn-secret`) |
| `AZURE-OPENAI-API-KEY` | computed via `listKeys()` on `openai-<prefix>-<env>` | be, worker, every job (`openai-key-secret`); read by `e2e-regression.yml` |
| `AZURE-DOC-INTEL-KEY` | computed via `listKeys()` on `docintel-<prefix>-<env>` | be, worker (`docintel-key-secret`); read by `e2e-regression.yml` |
| `AZURE-DOC-INTEL-KEY-2`, `-3`, `AZURE-DOC-INTEL-ENDPOINT-2`, `-3` | computed; only when `docIntelInstanceCount >= 2 / 3` (dev params: `1`) | worker only |
| `CLERK-SECRET-KEY` | `clerkSecretKey` in the secrets file | be, worker, fe, website, every job (`clerk-secret-secret`) |
| `TOKEN-ENCRYPTION-KEY` | `tokenEncryptionKey` (Fernet, see `infra/README.md`) | be, worker, every job (`token-encryption-secret`) |
| `GOOGLE-CLIENT-SECRET` | `googleClientSecret` | be, worker (`google-client-secret-secret`) — Google Drive connector |
| `SALESFORCE-CLIENT-SECRET` | `salesforceClientSecret` | be, worker (`salesforce-client-secret-secret`) — **residue**: the Salesforce connector was removed 2026-08-28 (Gap 334). Still declared in bicep and in the `.example`, so the file must still contain *a* value or Stage 5 fails validation; nothing reads it |
| `SENDGRID-API-KEY` | `sendgridApiKey` | be, worker (`sendgrid-key-secret` — name kept to match the value set live on 2026-08-26) |
| `SENDGRID-INBOUND-SECRET` | `sendgridInboundSecret` | be only (`sendgrid-inbound-secret` → env `INBOUND_PARSE_SHARED_SECRET`; also placed in the SendGrid Inbound Parse destination URL as `?key=`) |
| `PAYU-MERCHANT-KEY`, `PAYU-MERCHANT-SALT` | `payuMerchantKey`, `payuMerchantSalt` (test pair while `payuMode=test`) | be only |

Stage 5's template output `secretsSeeded = 13 + 2 × (docIntelInstanceCount − 1)`
is what `deploy-all.ps1` compares against `az keyvault secret list`
(`infra/README.md` still says "7", which is stale). Note there is no
`DATABASE-PASSWORD` secret — the password only exists inside `DATABASE-URL`.

Values that are **not** secrets and live in the committed `params.dev.json`
instead: `nextPublicClerkPublishableKey`, `clerkJwtIssuer`, `clerkJwksUrl`,
`googleClientId`, `salesforceClientId` (residue), the SendGrid addresses
(`sendgridSendingDomain`, `sendgridFromEmail`, `sendgridFromName`,
`emailAppDomain`, `emailAppAddress`, `supportNotifyEmail`), `payuMode`,
`alertEmail`, the model deployment names and the `enable*` feature flags.

`ALLOW_MOCK_AUTH` is never set by bicep; `config.py` (Gap 359) refuses to
start with it `true` unless `ENVIRONMENT` is a recognised non-production
value, so a deployed app cannot accidentally run with the auth bypass.

## Rotating a secret

1. Update the value in `infra/params.dev.secrets.json` locally (this file
   is gitignored — never commit real secrets). For the computed secrets
   (Postgres/Redis/Storage/OpenAI/DocIntel keys) rotate the key on the Azure
   resource instead; re-running Stage 5 re-reads it.
2. Re-run Stage 5 only. `deploy-all.ps1` filters both param files down to the
   names Stage 5 declares; when running `az` directly, pass only parameters
   `05-secrets.bicep` declares (ARM rejects unknown names):
   ```bash
   az deployment group create \
     --resource-group rg-invoice-llm-dev \
     --template-file infra/05-secrets.bicep \
     --parameters environment=dev namingPrefix=invoicellm \
                  postgresServerName=psql-invoice-llm-dev docIntelInstanceCount=1 \
                  manageDatabaseUrlSecret=true \
     --parameters @infra/params.dev.secrets.json
   ```
   Set `manageDatabaseUrlSecret=false` if the local `dbAdminPassword` cannot be
   trusted to match the live server (the server was recreated by hand at one
   point — `start-env.ps1` references `psql-invoice-llm-dev-v2`).
3. Verify the update landed:
   ```bash
   az keyvault secret list --vault-name kv-invoicellm-dev -o table
   ```
   (`kv-invoice-llm-dev-rb6z` is an orphaned duplicate vault listed in
   `infra/deployment_tracker.md` — ignore it.)
4. Container Apps resolve Key Vault references when a revision starts, so
   create a new revision (`az containerapp update` or a redeploy from
   `deploy-dev.yml`) for each app that uses the rotated secret. Jobs pick the
   new value up on their next execution.

Known caveat: `deploy-all.ps1` has historically not completed end-to-end on
dev and Stage 8 is blocked by Gap 298; a full environment rebuild is
deferred. Stage 5 on its own has been run successfully.

## GitHub repository secrets that do exist

Three Service Principal credential blobs (JSON from `az ad sp create-for-rbac`)
in **Settings → Secrets and variables → Actions** of the `Invoice_LLM` repo:

| Secret | Used by | Notes |
|---|---|---|
| `Azure_Dev_Credentials` | `deploy-dev.yml` (login for `resolve-fqdns`, all four deploys, `verify-deployment`) | case-sensitive name |
| `AZURE_CREDENTIALS_PROD` | `deploy-prod.yml` | jobs run under the `production` GitHub Environment (required reviewers) |
| `AZURE_CREDENTIALS` | `e2e-regression.yml` | needs Key Vault secret *read* on `kv-invoicellm-dev` |

No other GitHub repository secret is required or synced — there is no
GitHub-Secrets mirror of Key Vault to keep in sync.

## If automated sync is wanted in the future

Nothing here prevents building a real `sync-secrets.yml` workflow later,
but as of this writing it doesn't exist. If you add one, update this guide
and `infra/README.md`'s "GitHub CI/CD & Secrets Synchronization" section
to match, rather than leaving them describing aspirational tooling as if
it were live (this is exactly the drift that prompted this correction).
