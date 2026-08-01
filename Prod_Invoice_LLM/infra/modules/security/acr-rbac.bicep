targetScope = 'resourceGroup'

// AcrPull role assignment for the shared ACR registry, deployed with an
// explicit `scope:` on the module invocation in 07-rbac.bicep (see
// `scope: resourceGroup(acrResourceGroup)`) so it can target a different
// resource group than the rest of this deployment -- required because ACR
// is shared across dev/prod (one registry, owned by whichever environment
// deploys it in 03-data.bicep) and a cross-RG role assignment cannot be an
// inline resource in a template whose own targetScope is a single,
// different resource group. This module's own targetScope is still
// 'resourceGroup' (just a different one, bound at the call site) -- a
// plain resourceGroup-scoped role assignment works whether acrResourceGroup
// happens to equal the caller's own RG (dev, same-RG case) or not (prod,
// genuinely cross-RG case); no branching needed here.

param identityPrincipalId string
param acrName string

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource acrRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identityPrincipalId, acr.id, acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}
