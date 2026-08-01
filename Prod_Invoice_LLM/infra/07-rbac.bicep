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

@description('Name of the shared ACR registry this environment pulls from. Defaults to this environment\'s own computed name (dev, which owns it); prod must set this explicitly to the owning environment\'s registry name -- see 03-data.bicep.')
param sharedAcrName string = 'acr${replace(namingPrefix, '-', '')}${environment}'

@description('Resource group that owns the shared ACR registry. Defaults to this deployment\'s own resource group (dev); prod must set this explicitly to the owning environment\'s resource group name.')
param sharedAcrResourceGroup string = resourceGroup().name

var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
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
  }
}

// Cross-RG (shared ACR) AcrPull assignment -- see modules/security/acr-rbac.bicep
// for why this needs its own module with an explicit resource-group scope
// rather than being folded into rbacAssignments above. Works identically
// whether sharedAcrResourceGroup equals this deployment's own RG (dev,
// today) or a different one (prod, pulling dev's registry).
module acrRbac './modules/security/acr-rbac.bicep' = {
  name: 'acr-rbac-deploy'
  scope: resourceGroup(sharedAcrResourceGroup)
  params: {
    identityPrincipalId: identity.properties.principalId
    acrName: sharedAcrName
  }
}
