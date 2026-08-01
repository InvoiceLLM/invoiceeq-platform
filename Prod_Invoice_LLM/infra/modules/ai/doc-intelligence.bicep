param location string
param docIntelName string
param subnetId string
param privateDnsZoneId string

@description('Whether to provision private networking. false = public network access, key-auth reachable (dev); true = private-endpoint-only (prod).')
param networkIsolation bool = false

@description('Public network access when networkIsolation=false. Ignored (forced Disabled) when networkIsolation=true.')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: docIntelName
  location: location
  kind: 'FormRecognizer' // For Document Intelligence
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: networkIsolation ? 'Disabled' : publicNetworkAccess
    customSubDomainName: docIntelName
  }
}

// Private Endpoint for Document Intelligence
resource docIntelPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (networkIsolation) {
  name: '${docIntelName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${docIntelName}-connection'
        properties: {
          privateLinkServiceId: docIntelAccount.id
          groupIds: [
            'account'
          ]
        }
      }
    ]
  }
}

resource docIntelPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (networkIsolation) {
  parent: docIntelPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'docintel-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output docIntelId string = docIntelAccount.id
output endpoint string = docIntelAccount.properties.endpoint
