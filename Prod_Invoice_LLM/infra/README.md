# 10-Stage Deployment Strategy

Rebuilt 2026-07-22: the old 4-stage `main-step1..4.bicep` layout never
completed a clean end-to-end run — CLI-orchestrated stages don't carry
ARM's own dependency/readiness graph across separate `az deployment group
create` calls, so a stage could start before the previous one's resources
(Redis Enterprise especially) were actually ready, not just "deployment
succeeded." The stack is now 10 single-purpose files, each deployed and
verified before the next one starts:

| # | File | Creates | Verify |
|---|------|---------|--------|
| 1 | `01-network.bicep` | VNet, 4 subnets, 7 private DNS zones/links, 3 NSGs | `az network vnet show -g invoice-llm-dev -n vnet-invoice-llm-dev --query provisioningState -o tsv` |
| 2 | `02-security.bicep` | Managed identity, Key Vault + private endpoint | `az keyvault show -n kv-invoice-llm-dev -g invoice-llm-dev --query properties.provisioningState -o tsv` |
| 3 | `03-data.bicep` | PostgreSQL, Redis Enterprise, Storage, ACR | `az postgres flexible-server show -g invoice-llm-dev -n psql-invoice-llm-dev --query state -o tsv` (+ one check per resource, see `deploy-all.ps1`) |
| 4 | `04-ai.bicep` | Azure OpenAI, Document Intelligence (target: `publicNetworkAccess: Disabled`) | `az cognitiveservices account show -n openai-invoice-llm-dev -g invoice-llm-dev --query properties.provisioningState -o tsv` |
| 5 | `05-secrets.bicep` | Seeds the 7 Key Vault secrets from Stages 2-4's resources | `az keyvault secret list --vault-name kv-invoice-llm-dev --query "length(@)" -o tsv` (expect `7`) |
| 6 | `06-compute-env.bicep` | Container Apps Environment, ChromaDB | `az containerapp env show -g invoice-llm-dev -n cae-invoice-llm-dev --query properties.provisioningState -o tsv` |
| 7 | `07-rbac.bicep` | 5 role assignments for the managed identity | `az role assignment list --assignee <principalId> -g invoice-llm-dev -o table` (expect 5 rows) |
| 8 | `08-apps.bicep` | Backend, queue-worker, frontend container apps | `az containerapp show -g invoice-llm-dev -n ca-invoice-be-dev --query properties.runningStatus -o tsv` |
| 9 | `09-monitoring.bicep` | Log Analytics, App Insights, action group, diagnostic settings, ~16 alert rules | `az monitor metrics alert list -g invoice-llm-dev -o table` |
| 10 | `10-budget.bicep` | $150/month consumption budget, 80%/100% notifications | `az consumption budget list -o table` |

Run all 10 in order with `./deploy-all.ps1` — it runs each stage's `az
deployment group create` (blocking), then polls the stage's own
resource-readiness check above before starting the next one, and stops
immediately on the first failure.

**Do not run Stage 4 (or a full `deploy-all.ps1` run) while a local
benchmark/E2E run needs Azure OpenAI/Doc Intelligence reachable over the
public internet** — Stage 4's target state re-locks both to
private-endpoint-only, which will break the run.

Every resource name is hardcoded/computed to match what's already live in
`invoice-llm-dev`, so re-running any stage is an idempotent reconciliation,
never a recreation.

---

## Secrets

Two parameter files:

- **`params.dev.json`** — non-secret values, committed to git.
- **`params.dev.secrets.json`** — `dbAdminPassword`, `clerkSecretKey`,
  `tokenEncryptionKey`. **Gitignored** — copy
  `params.dev.secrets.json.example` to `params.dev.secrets.json` and fill
  in real values before running `deploy-all.ps1`. It's picked up
  automatically (or pass `-SecretsFile` explicitly).

### Token Encryption Key Setup

`tokenEncryptionKey` must be a valid 32-byte urlsafe base64-encoded key:

```powershell
.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the result in `params.dev.secrets.json`. Stage 5 seeds it into Key
Vault.

---

## GitHub CI/CD & Secrets Synchronization

To configure the automated GitHub Actions CI/CD pipeline and synchronize secrets between Azure Key Vault and GitHub:

1. **GitHub Workflow Permissions**:
   * Navigate to **Settings → Actions → General → Workflow permissions**.
   * Select **"Read and write permissions"** and click Save (this is required for the sync workflow to update secrets).

2. **Add Azure Credentials**:
   * Navigate to **Settings → Secrets and variables → Actions**.
   * Create a new repository secret named `AZURE_CREDENTIALS` containing your Azure Service Principal credentials (in JSON format).

3. **Secrets Synchronization**:
   * The repository uses a daily automated sync workflow (`.github/workflows/sync-secrets.yml`) to sync secrets from Azure Key Vault directly to GitHub Repository Secrets (e.g. `DB_ADMIN_PASSWORD`, `CLERK_SECRET_KEY`, etc.).
   * To trigger a sync manually, go to the **Actions** tab on GitHub, select **"Sync Azure Key Vault Secrets to GitHub"**, and click **"Run workflow"**.
   * *For more details, see `docs/guides/SECRETS_SYNC_GUIDE.md`.*
