targetScope = 'resourceGroup'

// ================= Parameters =================
@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Azure OpenAI Model Version - verify current availability before deploying: az cognitiveservices account list-models --location <region> -o table')
param azureOpenAiModelVersion string

@description('VNet name from step1')
param vnetName string

// ================= Variables =================
var keyVaultName = 'kv-${namingPrefix}-${environment}-${substring(uniqueString(resourceGroup().id), 0, 4)}'

// Get VNet outputs from existing deployment
module network './modules/network/vnet.bicep' = {
  name: 'network-reference'
  params: {
    location: location
    vnetName: vnetName
  }
}

// ================= 1. Cognitive & AI Services =================
module openai './modules/ai/openai.bicep' = {
  name: 'openai-deploy'
  params: {
    location: location
    openaiName: 'openai-${namingPrefix}-${environment}'
    deploymentName: azureOpenAiDeploymentName
    modelName: azureOpenAiDeploymentName
    modelVersion: azureOpenAiModelVersion
    subnetId: network.outputs.aiSubnetId
    privateDnsZoneId: network.outputs.openaiDnsZoneId
  }
}

module docIntelligence './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}'
    subnetId: network.outputs.aiSubnetId
    privateDnsZoneId: network.outputs.docIntelDnsZoneId
  }
}

// ================= Outputs =================
output openaiEndpoint string = openai.outputs.endpoint
output docIntelEndpoint string = docIntelligence.outputs.endpoint
