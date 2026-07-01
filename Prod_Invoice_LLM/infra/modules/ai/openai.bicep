param location string
param openaiName string
param deploymentName string = 'gpt-4o-mini'
param subnetId string
param privateDnsZoneId string

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openaiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Disabled'
    customSubDomainName: openaiName
  }
}

// Deploy OpenAI Model
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openaiAccount
  name: deploymentName
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
  }
  sku: {
    name: 'Standard'
    capacity: 20 // 20k TPM for Dev
  }
}

// Private Endpoint for OpenAI
resource openaiPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = {
  name: '${openaiName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${openaiName}-connection'
        properties: {
          privateLinkServiceId: openaiAccount.id
          groupIds: [
            'cognitiveServices'
          ]
        }
      }
    ]
  }
}

resource openaiPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = {
  parent: openaiPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'openai-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output openaiId string = openaiAccount.id
output endpoint string = openaiAccount.properties.endpoint
