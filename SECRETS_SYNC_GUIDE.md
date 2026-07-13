# Azure Key Vault to GitHub Secrets Synchronization

## Overview

This document explains how to synchronize secrets between Azure Key Vault and GitHub Secrets for the Invoice-LLM project. This ensures that GitHub Actions has access to the latest secrets without manual updates.

## Architecture

```
Azure Key Vault (Source) → GitHub Actions → GitHub Secrets (Destination)
```

**Flow:**
1. Azure Key Vault stores all application secrets (DB passwords, API keys, etc.)
2. GitHub Actions workflow runs daily or on-demand
3. Workflow downloads secrets from Azure Key Vault
4. Workflow updates corresponding GitHub Secrets
5. GitHub Actions workflows use GitHub Secrets for deployments

## Secret Mapping

| Azure Key Vault Secret | GitHub Secret | Description |
|------------------------|---------------|-------------|
| DATABASE-PASSWORD | DB_ADMIN_PASSWORD | PostgreSQL admin password |
| CLERK-SECRET-KEY | CLERK_SECRET_KEY | Clerk SSO secret key |
| TOKEN-ENCRYPTION-KEY | TOKEN_ENCRYPTION_KEY | Fernet encryption key for tokens |
| AZURE-OPENAI-API-KEY | AZURE_OPENAI_API_KEY | Azure OpenAI API key |
| AZURE-DOC-INTEL-KEY | AZURE_DOC_INTEL_KEY | Azure Document Intelligence API key |

## Setup Instructions

### 1. Prerequisites

- Azure Service Principal with Key Vault access
- GitHub repository with Actions enabled
- `AZURE_CREDENTIALS` secret already configured in GitHub

### 2. Configure GitHub Permissions

The sync workflow requires `contents: write` permission to update secrets. Add this to your repository:

**Settings → Actions → General → Workflow permissions:**
- Select "Read and write permissions"

### 3. Initial GitHub Secrets Setup

Configure these secrets in GitHub (Settings → Secrets and variables → Actions):

**Required:**
- `AZURE_CREDENTIALS` - Azure service principal credentials (JSON format)

**Optional (will be synced from Azure):**
- `DB_ADMIN_PASSWORD` - PostgreSQL password
- `CLERK_SECRET_KEY` - Clerk secret key
- `TOKEN_ENCRYPTION_KEY` - Token encryption key
- `AZURE_OPENAI_API_KEY` - OpenAI API key
- `AZURE_DOC_INTEL_KEY` - Document Intelligence API key

### 4. Grant Service Principal Key Vault Access

Ensure your Azure Service Principal has these permissions on Key Vault:

```bash
# Get your service principal object ID
SP_ID=$(az ad sp show --id <your-client-id> --query objectId -o tsv)

# Grant Key Vault access
az keyvault set-policy --name <keyvault-name> \
  --object-id $SP_ID \
  --secret-permissions get list
```

## Usage

### Automatic Sync (Daily)

The workflow runs automatically daily at 2 AM UTC to sync any secret changes.

### Manual Sync

1. Go to GitHub Actions tab in your repository
2. Select "Sync Azure Key Vault Secrets to GitHub" workflow
3. Click "Run workflow"
4. Enter your Key Vault name (or leave blank for auto-detection)
5. Click "Run workflow"

### View Sync Status

After sync completes, check the `SECRETS.md` file in your repository root for:
- Last sync timestamp
- List of all secrets in Key Vault
- Secret mapping reference

## Troubleshooting

### Workflow Fails with "No Key Vault found"

**Solution:** Provide the Key Vault name manually when triggering the workflow, or ensure the resource group name matches your deployment.

### Secrets Not Updating

**Solution:** 
1. Check that your Service Principal has Key Vault access
2. Verify GitHub Actions has write permissions
3. Check workflow logs for specific error messages

### GitHub CLI Authentication Error

**Solution:** The workflow uses GitHub CLI internally. Ensure your repository has the correct permissions enabled.

## Security Considerations

- **Single Source of Truth:** Azure Key Vault remains the source of truth
- **Read-Only Sync:** GitHub Secrets are only updated from Azure, never the reverse
- **Audit Trail:** All secret syncs are logged in GitHub Actions
- **Least Privilege:** Service Principal only needs Key Vault read access

## Deployment Integration

The main deployment workflow (`.github/workflows/deploy-dev.yml`) uses GitHub Secrets for:

```yaml
- name: Deploy to Azure Container Apps
  uses: azure/arm-deploy@v2
  with:
    parameters: >
      dbAdminPassword=${{ secrets.DB_ADMIN_PASSWORD }}
      clerkSecretKey=${{ secrets.CLERK_SECRET_KEY }}
      # ... other secrets
```

**Note:** With the new staged deployment approach using `deploy-all.ps1`, these GitHub Secrets are not used since the Bicep files handle secret seeding directly from parameters. However, keeping them in sync provides a backup and enables other workflows that might need them.

## File Structure

```
.github/
  workflows/
    sync-secrets.yml          # Secret sync workflow
    deploy-dev.yml            # Main deployment workflow

SECRETS.md                   # Auto-generated secret documentation
```

## Next Steps After Deployment

After running the staged deployment:

1. **Verify Key Vault Secrets:**
   ```bash
   az keyvault secret list --vault-name <kv-name> -o table
   ```

2. **Run Initial Sync:**
   - Trigger the sync workflow manually
   - Verify GitHub Secrets are updated

3. **Test Deployment:**
   - Ensure GitHub Actions can access secrets
   - Run a test deployment

## Maintenance

- **Rotate Secrets:** Update in Azure Key Vault, then run sync workflow
- **Add New Secrets:** Add to Key Vault, update mapping in `sync-secrets.yml`, run sync
- **Remove Secrets:** Remove from Key Vault, remove from GitHub Secrets manually

## Support

For issues with:
- **Azure Key Vault:** Check Azure Portal → Key Vault → Access policies
- **GitHub Actions:** Check Actions tab → Workflow runs → Logs
- **Service Principal:** Check Azure AD → App registrations → Certificates & secrets
