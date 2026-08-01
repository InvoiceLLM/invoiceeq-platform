param location string
param acrName string
param subnetId string
param privateDnsZoneId string

@description('Public network access for ACR. Must stay Enabled for GitHub-hosted CI runners to push images over the public internet. Container Apps still pull privately via the VNet private endpoint below regardless of this setting - the two are independent paths.')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

@description('Whether to also provision a private endpoint into this deployment\'s VNet (requires Stage 1 to have run, i.e. networkIsolation=true for whichever environment owns this ACR). false = no PE is created; the registry is reachable only via its public endpoint (still auth-gated by AcrPull RBAC / admin credentials), which is also what CI push always uses regardless of this setting.')
param deployPrivateEndpoint bool = false

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Premium' // Premium is required for Private Endpoints
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: publicNetworkAccess
  }
}

// Private Endpoint for Azure Container Registry
resource acrPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (deployPrivateEndpoint) {
  name: '${acrName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${acrName}-connection'
        properties: {
          privateLinkServiceId: acr.id
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

// Private DNS Zone Group config for the PE
resource acrPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (deployPrivateEndpoint) {
  parent: acrPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'acr-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output acrId string = acr.id
output loginServer string = acr.properties.loginServer
