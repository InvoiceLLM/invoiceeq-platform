param identityPrincipalId string
param storageAccountName string
param openaiName string
param docIntelName string
param keyVaultName string

// Role Definition IDs (Azure Standard Roles)
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
// Feature 20 Area 1. Verified against this subscription on 2026-08-23 with
// `az role definition list --name "Cost Management Reader"` rather than copied
// from documentation.
var costManagementReader = '72fafb9e-0641-4937-9268-a91bfd8191a3'
// Feature 24 (Ops Digest Agent). Same check, same day: `az role definition list
// --name "Monitoring Reader"` on this subscription returns actions
// `*/read` + `Microsoft.OperationalInsights/workspaces/search/action` +
// `Microsoft.Support/*`. Read-only.
var monitoringReader = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

// ACR's AcrPull assignment is NOT here -- ACR is a shared resource that may
// live in a different resource group than this deployment (prod pulling
// dev's registry), and a cross-RG role assignment cannot be an inline
// resource in a template whose targetScope is this deployment's own
// resource group. See modules/security/acr-rbac.bicep + this stage's
// acrRbac module invocation (07-rbac.bicep), which handles both the
// same-RG (dev) and cross-RG (prod) cases via `scope: resourceGroup(...)`.

// Reference existing resources
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName
}

// RBAC for Storage Account
resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, storageAccount.id, storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC for OpenAI
resource openaiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, openaiAccount.id, cognitiveServicesUser)
  scope: openaiAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC for Document Intelligence
resource docIntelRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, docIntelAccount.id, cognitiveServicesUser)
  scope: docIntelAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Reference existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// RBAC for Cost Management (Feature 20 Area 1 — `apps/invoice-be/services/azure_cost.py`)
//
// The only assignment in this file scoped to the *resource group* rather than a
// single resource: Cost Management has no per-resource scope to grant on, and
// the three calls that module makes are all against
// `{resourceGroupScope}/providers/Microsoft.CostManagement|Consumption/...`.
// RG scope is deliberately the narrowest that works -- a subscription-scoped
// grant would also expose spend for anything else that ever lands in this
// subscription.
//
// Why this exact role, checked rather than assumed (2026-08-23): the two
// operations this app calls register as `Microsoft.CostManagement/query/read`
// and `Microsoft.CostManagement/forecast/read` (`/read`, despite both being
// HTTP POSTs -- confirmed via `az provider operation show --namespace
// Microsoft.CostManagement`), so they are covered by Cost Management Reader's
// `Microsoft.CostManagement/*/read`; reading `budget-invoicellm-dev` is covered
// by its `Microsoft.Consumption/*/read`. It is a read-only role: it grants no
// ability to create, edit or delete the budget it reads.
resource costManagementRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, resourceGroup().id, costManagementReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', costManagementReader)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC for the Ops Digest Agent (Feature 24 — `apps/invoice-be/services/ops_digest*.py`)
//
// `caj-ops-digest-<env>` makes two ARM reads that no existing assignment covers:
//
//   1. Azure Resource Graph over `alertsmanagementresources` — which alerts
//      fired in the last window.
//   2. `microsoft.insights/actionGroups/{name}/read` — where critical alerts are
//      actually delivered, so the digest goes to the same Teams webhook + email
//      rather than to a second copy of that configuration which can drift.
//
// Monitoring Reader is the smallest built-in role covering both. Its actions on
// this subscription are exactly `*/read`, `Microsoft.OperationalInsights/
// workspaces/search/action` and `Microsoft.Support/*` (checked 2026-08-23, not
// copied from docs) — read-only, and it cannot modify or acknowledge an alert.
//
// **Scope caveat, stated rather than assumed.** This is RG-scoped, matching the
// cost assignment above and following the same narrowest-that-works principle.
// Fired alert instances come back from Resource Graph carrying
// `resourceGroup: rg-invoice-llm-dev`, so an RG-scoped read *should* return
// them — but Resource Graph's own access model is not something that can be
// confirmed from the template, and this assignment has **not been deployed**
// (Stage 7 has not been redeployed since Gap 297 either). If a live run of
// `scripts/ops_digest_job.py` inside the container comes back with zero alerts
// while the portal shows some, this scope is the first thing to widen to
// subscription level — not the code.
resource monitoringReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, resourceGroup().id, monitoringReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReader)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC for Key Vault (Secrets User — allows Container Apps to read secrets)
resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, keyVault.id, keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

