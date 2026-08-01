targetScope = 'resourceGroup'

// ================= Stage 4: Cognitive AI Services =================
// Azure OpenAI + Document Intelligence. Depends on Stage 1 only.
// Target state is publicNetworkAccess: Disabled (private-endpoint-only,
// per Cloud_Architecture_Document.md §6) when networkIsolation=true (prod).
// NOTE: live OpenAI/DocIntel are currently manually flipped to Enabled for
// benchmark testing — running this stage with networkIsolation=true
// reverts that. Do not run until benchmark testing is done.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Whether to provision private networking. false = public/key-auth access (dev); true = private-endpoint-only (prod).')
param networkIsolation bool = false

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Azure OpenAI Model Version - verify current availability before deploying: az cognitiveservices account list-models --location <region> -o table')
param azureOpenAiModelVersion string

@description('Azure OpenAI GlobalStandard deployment TPM capacity. Dev should stay low (e.g. 100) so it does not claim TPM headroom prod needs; prod can go higher (e.g. 500).')
param openAiCapacity int = 100

@description('Number of Document Intelligence resources to deploy (1-3). Each S0 resource has its own independent 15 req/10s rate limit; the app round-robins across all configured endpoints (utils/doc_intel_client.py). Dev=1, prod=3.')
@minValue(1)
@maxValue(3)
param docIntelInstanceCount int = 1

var vnetName = 'vnet-${namingPrefix}-${environment}'
var aiSubnetId = networkIsolation ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-ai') : ''
var openaiDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.openai.azure.com') : ''
var docIntelDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.cognitiveservices.azure.com') : ''

module openai './modules/ai/openai.bicep' = {
  name: 'openai-deploy'
  params: {
    location: location
    openaiName: 'openai-${namingPrefix}-${environment}'
    deploymentName: azureOpenAiDeploymentName
    modelName: azureOpenAiDeploymentName
    modelVersion: azureOpenAiModelVersion
    networkIsolation: networkIsolation
    subnetId: aiSubnetId
    privateDnsZoneId: openaiDnsZoneId
    capacity: openAiCapacity
  }
}

module docIntelligence './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}'
    networkIsolation: networkIsolation
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
// Gated on docIntelInstanceCount so dev (=1) doesn't pay for capacity it
// doesn't need while prod (=3) still gets full horizontal scale-out.
module docIntelligence2 './modules/ai/doc-intelligence.bicep' = if (docIntelInstanceCount >= 2) {
  name: 'docintel2-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}-2'
    networkIsolation: networkIsolation
    subnetId: aiSubnetId
    privateDnsZoneId: docIntelDnsZoneId
  }
}

module docIntelligence3 './modules/ai/doc-intelligence.bicep' = if (docIntelInstanceCount >= 3) {
  name: 'docintel3-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}-3'
    networkIsolation: networkIsolation
    subnetId: aiSubnetId
    privateDnsZoneId: docIntelDnsZoneId
  }
}

// ================= Outputs =================
output openaiEndpoint string = openai.outputs.endpoint
output docIntelEndpoint string = docIntelligence.outputs.endpoint
output docIntelEndpoint2 string = docIntelligence2.?outputs.?endpoint ?? ''
output docIntelEndpoint3 string = docIntelligence3.?outputs.?endpoint ?? ''
