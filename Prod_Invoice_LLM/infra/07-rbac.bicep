targetScope = 'resourceGroup'

// ================= Stage 7: RBAC Assignments =================
// Depends on Stage 2 (identity + vault), 3 (storage/ACR), 4 (OpenAI/DocIntel).
// Fix vs. the old main-step4.bicep: that file re-invoked the *creating*
// vnet.bicep module a second time purely to read its outputs. This stage
// needs no network outputs at all, so that whole pattern is gone.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var identityName = 'id-${namingPrefix}-${environment}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

module rbacAssignments './modules/security/rbac-assignments.bicep' = {
  name: 'rbac-assignments-deploy'
  params: {
    identityPrincipalId: identity.properties.principalId
    storageAccountName: storageAccountName
    openaiName: openaiName
    docIntelName: docIntelName
    keyVaultName: keyVaultName
    acrName: acrName
  }
}
