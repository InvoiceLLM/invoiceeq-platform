targetScope = 'resourceGroup'

// ================= Stage 2: Identity + Key Vault =================
// Depends on Stage 1 (subnet + KV private DNS zone). Creates the vault
// and its network plumbing only — secret *values* are seeded in Stage 5,
// once the resources those secrets describe (Stage 3/4) actually exist.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Whether to provision private networking. false = Key Vault is public/RBAC-auth only (dev); true = private-endpoint-only (prod). Must match Stage 1.')
param networkIsolation bool = false

var vnetName = 'vnet-${namingPrefix}-${environment}'
// Fixed name, matching the vault actually wired into the live Container
// Apps today — the old main-step1/2.bicep computed a random-suffixed name
// here instead, which is how the orphaned kv-invoice-llm-dev-rb6z vault
// was created.
var keyVaultName = 'kv-${namingPrefix}-${environment}'

// Subnet + DNS zone IDs are deterministic ARM resource IDs — computed
// directly rather than by re-invoking Stage 1's creating module. Empty
// when networkIsolation=false since Stage 1 never created them.
var peSubnetId = networkIsolation ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-pe') : ''
var keyVaultDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.vaultcore.azure.net') : ''

module identities './modules/security/managed-identities.bicep' = {
  name: 'managed-identities-deploy'
  params: {
    location: location
    identityName: 'id-${namingPrefix}-${environment}'
  }
}

module keyVault './modules/security/keyvault.bicep' = {
  name: 'keyvault-deploy'
  params: {
    location: location
    keyVaultName: keyVaultName
    networkIsolation: networkIsolation
    subnetId: peSubnetId
    privateDnsZoneId: keyVaultDnsZoneId
  }
}

// ================= Outputs =================
output keyVaultName string = keyVaultName
output identityId string = identities.outputs.identityId
output identityClientId string = identities.outputs.clientId
output identityPrincipalId string = identities.outputs.principalId
