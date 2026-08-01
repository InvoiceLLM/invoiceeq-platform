# Creating a New Environment

## How the files fit together

- **`infra/01-network.bicep` … `10-budget.bicep`** — orchestrators. These
  are the only files you ever deploy directly. Each one calls into
  `modules/**` and wires one stage's outputs into the next.
- **`infra/modules/<category>/*.bicep`** — reusable building blocks (one
  Azure resource type each: `vnet.bicep`, `keyvault.bicep`,
  `postgresql.bicep`, etc.). Never deployed directly — referenced by the
  stage files via `module xyz './modules/.../foo.bicep' = { ... }`.

Stage files = **what to run, in what order**. Modules = **how each
resource is actually built**. As long as `infra/modules/` sits next to the
numbered stage files, everything resolves automatically via relative
paths — you don't touch it.

## Steps to stand up a new environment

1. **Create the secrets file** (never commit this — it's gitignored):
   ```
   cp infra/params.dev.secrets.json.example infra/params.<env>.secrets.json
   ```
   Fill in real values for `dbAdminPassword`, `clerkSecretKey`, and a fresh
   `tokenEncryptionKey`:
   ```powershell
   .venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **Create the non-secret params file**:
   ```
   cp infra/params.dev.json infra/params.<env>.json
   ```
   Update `environment`, `namingPrefix` (if it's a different client/naming
   scheme), `location`, container image tags, `alertEmail`, and
   `monthlyBudgetAmount` for the new environment.

3. **Run the orchestrator**:
   ```powershell
   ./infra/deploy-all.ps1 -Environment <env> -ResourceGroup rg-<name> -Location <region> -NamingPrefix <prefix>
   ```
   This does everything else automatically:
   - Creates the resource group if it doesn't exist.
   - Runs Stages 1 → 10 in strict order, one `az deployment group create`
     each.
   - After every stage, polls that stage's own resource-readiness check
     (not just "ARM accepted the deployment") before starting the next
     one — e.g. it won't start Stage 4 until Stage 3's Postgres server
     actually reports `Ready` and Redis reports `Running`.
   - Stops immediately with a clear message on the first stage that fails,
     so you always know exactly which stage broke.

4. **Nothing else to do manually** — `modules/` is found automatically via
   relative paths from each stage file.

## Stage reference

| # | File | Creates |
|---|------|---------|
| 1 | `01-network.bicep` | VNet, 4 subnets, 7 private DNS zones/links, 3 NSGs |
| 2 | `02-security.bicep` | Managed identity, Key Vault + private endpoint |
| 3 | `03-data.bicep` | PostgreSQL, Redis Enterprise, Storage, ACR |
| 4 | `04-ai.bicep` | Azure OpenAI, Document Intelligence (private-endpoint-only) |
| 5 | `05-secrets.bicep` | Seeds the 7 Key Vault secrets from Stages 2-4's resources |
| 6 | `06-compute-env.bicep` | Container Apps Environment, ChromaDB |
| 7 | `07-rbac.bicep` | Role assignments for the managed identity |
| 8 | `08-apps.bicep` | Backend, queue-worker, frontend, and website container apps |
| 9 | `09-monitoring.bicep` | Log Analytics, App Insights, action group, diagnostics, health alerts |
| 10 | `10-budget.bicep` | Monthly consumption budget + cost alerts |

## One thing to watch

Resource names are computed as `<prefix>-${namingPrefix}-${environment}`
(e.g. `kv-invoice-llm-dev`). Pick a `-NamingPrefix`/`-Environment`
combination that's unique to this environment — reusing an existing
combo in the same subscription will reconcile against (not duplicate)
whatever's already there, since every stage is idempotent by design.
Deploying into a different subscription is always safe regardless, since
names only need to be unique within their own subscription/resource group.
