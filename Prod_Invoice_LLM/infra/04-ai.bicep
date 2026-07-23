targetScope = 'resourceGroup'

// ================= Stage 4: Cognitive AI Services =================
// Azure OpenAI + Document Intelligence. Depends on Stage 1 only.
// Target state is publicNetworkAccess: Disabled (private-endpoint-only,
// per Cloud_Architecture_Document.md §6). NOTE: live OpenAI/DocIntel are
// currently manually flipped to Enabled for benchmark testing — running
// this stage reverts that. Do not run until benchmark testing is done.

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

var vnetName = 'vnet-${namingPrefix}-${environment}'
var aiSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-ai')
var openaiDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.openai.azure.com')
var docIntelDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.cognitiveservices.azure.com')

module openai './modules/ai/openai.bicep' = {
  name: 'openai-deploy'
  params: {
    location: location
    openaiName: 'openai-${namingPrefix}-${environment}'
    deploymentName: azureOpenAiDeploymentName
    modelName: azureOpenAiDeploymentName
    modelVersion: azureOpenAiModelVersion
    subnetId: aiSubnetId
    privateDnsZoneId: openaiDnsZoneId
  }
}

module docIntelligence './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}'
    subnetId: aiSubnetId
    privateDnsZoneId: docIntelDnsZoneId
  }
}

// Two additional Doc Intelligence resources (Jul 2026, Gap 41/42 scaling work) -
// each S0 tier gets its own independent 15 req/10s rate limit (unlike Azure
// OpenAI, Doc Intelligence has no shared regional quota pool), so horizontal
// scale-out via multiple resources is the effective lever here. 3 resources
// combined = ~270 req/min vs. a single resource's ~90 req/min. The app
// round-robins across all configured endpoints (utils/doc_intel_client.py).
module docIntelligence2 './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel2-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}-2'
    subnetId: aiSubnetId
    privateDnsZoneId: docIntelDnsZoneId
  }
}

module docIntelligence3 './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel3-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}-3'
    subnetId: aiSubnetId
    privateDnsZoneId: docIntelDnsZoneId
  }
}

// ================= Outputs =================
output openaiEndpoint string = openai.outputs.endpoint
output docIntelEndpoint string = docIntelligence.outputs.endpoint
output docIntelEndpoint2 string = docIntelligence2.outputs.endpoint
output docIntelEndpoint3 string = docIntelligence3.outputs.endpoint
