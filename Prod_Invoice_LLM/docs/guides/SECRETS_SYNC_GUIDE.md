# Azure Key Vault & GitHub Actions Secrets — How It Actually Works

## Correction (2026-08-01)

This document previously described an automated daily GitHub Actions
workflow (`sync-secrets.yml`) that synced secrets from Azure Key Vault to
GitHub Repository Secrets. **That workflow does not exist and never has** —
`.github/workflows/` contains only `deploy-dev.yml` and
`e2e-regression.yml`. The section below describes the process that is
actually in place.

## Overview

There is no automated secret synchronization between Azure Key Vault and
GitHub. Application secrets are seeded into Key Vault manually, once, via
the staged bicep deployment; CI never touches them.

## How secrets actually flow

```
infra/params.dev.secrets.json (local, gitignored)
        │
        │  manually run once (or on rotation)
        ▼
Stage 5 (infra/05-secrets.bicep) via deploy-all.ps1 or a direct
`az deployment group create --template-file 05-secrets.bicep ...`
        │
        ▼
Azure Key Vault (kv-invoice-llm-dev) — persists independently after this;
container apps (08-apps.bicep) read secrets from Key Vault at runtime via
managed identity, not from GitHub.
```

`.github/workflows/deploy-dev.yml` never runs bicep and never re-syncs Key
Vault secrets. The only secret it reads from GitHub is `AZURE_CREDENTIALS`,
used for `az login` against Azure. The single non-secret exception is
`nextPublicClerkPublishableKey`, which the workflow reads straight from the
committed `infra/params.dev.json` (it's a public browser-bundle value, not
a secret, so it doesn't need Key Vault or GitHub Secrets at all).

## Secret Mapping (for reference — seeded into Key Vault by Stage 5, not GitHub)

| Azure Key Vault Secret | Source (local file) | Description |
|------------------------|----------------------|-------------|
| DATABASE-PASSWORD | `infra/params.dev.secrets.json` | PostgreSQL admin password |
| CLERK-SECRET-KEY | `infra/params.dev.secrets.json` | Clerk SSO secret key |
| TOKEN-ENCRYPTION-KEY | `infra/params.dev.secrets.json` | Fernet encryption key for tokens |
| AZURE-OPENAI-API-KEY | `infra/params.dev.secrets.json` | Azure OpenAI API key |
| AZURE-DOC-INTEL-KEY | `infra/params.dev.secrets.json` | Azure Document Intelligence API key |

(See `infra/params.dev.secrets.json.example` for the full parameter shape —
Stage 5 seeds 7 secrets total per `infra/README.md`'s Stage 5 verification
step.)

## Rotating a secret

1. Update the value in `infra/params.dev.secrets.json` locally (this file
   is gitignored — never commit real secrets).
2. Re-run Stage 5 only:
   ```bash
   az deployment group create \
     --resource-group invoice-llm-dev \
     --template-file infra/05-secrets.bicep \
     --parameters @infra/params.dev.json --parameters @infra/params.dev.secrets.json
   ```
3. Verify the update landed:
   ```bash
   az keyvault secret list --vault-name kv-invoice-llm-dev -o table
   ```
4. Restart/revision any container app that caches the old value in-process,
   if applicable.

## GitHub repository secrets that do exist

Only `AZURE_CREDENTIALS` (Azure Service Principal credentials, JSON format)
is required in **Settings → Secrets and variables → Actions**, for
`deploy-dev.yml`'s `az login` step. No other GitHub repository secret is
required or synced — there's no GitHub-Secrets mirror of Key Vault to keep
in sync.

## If automated sync is wanted in the future

Nothing here prevents building a real `sync-secrets.yml` workflow later,
but as of this writing it doesn't exist. If you add one, update this guide
and `infra/README.md`'s "GitHub CI/CD & Secrets Synchronization" section
to match, rather than leaving them describing aspirational tooling as if
it were live (this is exactly the drift that prompted this correction).
