param location string
param docIntelName string
param subnetId string
param privateDnsZoneId string

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: docIntelName
  location: location
  kind: 'FormRecognizer' // For Document Intelligence
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Disabled'
    customSubDomainName: docIntelName
  }
}

// Private Endpoint for Document Intelligence
resource docIntelPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = {
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
            'cognitiveServices'
          ]
        }
      }
    ]
  }
}

resource docIntelPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = {
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
output apiKey string = docIntelAccount.listKeys().key1
