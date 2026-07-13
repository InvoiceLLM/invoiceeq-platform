# Multi-Stage Deployment Strategy

Dependency Resolution: To circumvent circular dependency locks (e.g. key vault needing database endpoints while databases need key vault roles/identities), the codebase features split orchestration templates:

* **Step 1 (main-step1.bicep)**: Core infrastructure (VNet, Identities, Databases, Storage, ACR).
* **Step 2 (main-step2.bicep)**: Cognitive AI resources (OpenAI, Document Intelligence) and key seeding.
* **Step 3 (main-step3.bicep)**: ACA environment setup and ChromaDB.
* **Step 4 (main-step4.bicep)**: App containers deployment and RBAC roles mapping.

This 4-stage process is executed automatically via the `deploy-all.ps1` script.

---

## Token Encryption Key Setup

The `tokenEncryptionKey` parameter in `params.dev.json` must be a valid 32-byte urlsafe base64-encoded key. You can generate a new key using the following Python command in the backend virtual environment:

```powershell
.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Once generated, set the value of `"tokenEncryptionKey"` in `params.dev.json` to the generated string. Bicep will automatically seed this into Azure Key Vault during the Stage 1 deployment.

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
   * *For more details, see the parent directory's `SECRETS_SYNC_GUIDE.md`.*


