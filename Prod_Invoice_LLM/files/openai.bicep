param location string
param openaiName string
param deploymentName string = 'gpt-5-mini'
param subnetId string
param privateDnsZoneId string

@description('OpenAI model name to deploy. Verify current availability first: az cognitiveservices account list-models --location <region> -o table')
param modelName string = 'gpt-5-mini'

@description('Model version string. Do NOT guess this - the GPT-4.x line is actively being retired as of mid-2026. Get the exact current version with: az cognitiveservices account list-models --location <region> --query "[?name==\'gpt-5-mini\']" -o table')
param modelVersion string

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
// NOTE: gpt-4o-mini (2024-07-18) and gpt-4.1-mini (2025-04-14) have both hit
// deprecation as of mid-2026 - the entire GPT-4.x/4o line is being consolidated
// into GPT-5.x. modelName/modelVersion are left as required params rather than
// hardcoded so you confirm current availability at deploy time instead of
// inheriting another stale guess. Check with:
//   az cognitiveservices account list-models --location <region> -o table
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openaiAccount
  name: deploymentName
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
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
            'account'
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
