param identityPrincipalId string
param storageAccountName string
param openaiName string
param docIntelName string
param keyVaultName string

// Role Definition IDs (Azure Standard Roles)
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesUser = '14e7a4ae-c3c2-489c-85f2-2a00e0007bc1'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

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
