param identityPrincipalId string
param storageAccountName string
param openaiName string
param docIntelName string
param keyVaultName string

// Role Definition IDs (Azure Standard Roles)
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

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

