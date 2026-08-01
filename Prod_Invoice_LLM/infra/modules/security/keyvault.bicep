param location string
param keyVaultName string
param subnetId string
param privateDnsZoneId string

@description('Whether to provision private networking. false = public network access enabled, RBAC-auth still required (dev); true = private-endpoint-only (prod).')
param networkIsolation bool = false

// Target state: private-endpoint-only, matching Cloud_Architecture_Document.md's
// "Private by Default" principle. Secret *values* are seeded separately in
// 05-secrets.bicep, once the data/AI resources this vault stores connection
// info for actually exist — this module only creates the vault + network
// plumbing, so it has no dependency on anything downstream of it.
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enabledForDeployment: true
    enabledForTemplateDeployment: true
    enabledForDiskEncryption: true
    publicNetworkAccess: networkIsolation ? 'Disabled' : 'Enabled'
    networkAcls: {
      defaultAction: networkIsolation ? 'Deny' : 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (networkIsolation) {
  name: '${keyVaultName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${keyVaultName}-connection'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (networkIsolation) {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vault-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output keyVaultId string = keyVault.id
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultName string = keyVault.name
