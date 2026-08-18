targetScope = 'resourceGroup'

// ================= Stage 6: Container Apps Environment + ChromaDB =================
// Depends on Stage 1 (aca subnet) and Stage 3 (storage account for the
// ChromaDB file share).
//
// Log Analytics workspace creation lives HERE, not in Stage 9, even though
// it's conceptually a "monitoring" resource: container-env.bicep's
// appLogsConfiguration needs the workspace to already exist at CAE-create
// time, but Stage 9 (which used to create it) runs after Stage 6 in
// deploy-all.ps1's sequence -- a real ordering bug that meant the CAE could
// never have been wired to a workspace that existed yet. Rather than
// renumber every stage or add a new stage 0, the workspace module simply
// moves to whichever stage actually needs it to exist first; Stage 9 now
// references it via `existing` (see 09-monitoring.bicep).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Whether to provision private networking. false = Consumption CAE, Microsoft-managed networking (dev); true = VNet-injected CAE (prod).')
param networkIsolation bool = false

@description('Log Analytics retention in days. 30 (free-tier default) is enough for dev; prod should raise this (e.g. 90).')
param logRetentionInDays int = 30

@description('ChromaDB Container App vCPU allocation.')
param chromaDbCpu string = '0.5'

@description('ChromaDB Container App memory allocation.')
param chromaDbMemory string = '1.0Gi'

var vnetName = 'vnet-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var lawName = 'law-${namingPrefix}-${environment}'
// Hyphens stripped from namingPrefix, matching the real live resource
// (`appi-invoicellm-dev`, not `appi-invoice-llm-dev`) -- see 08-apps.bicep.
var appInsightsName = 'appi-${replace(namingPrefix, '-', '')}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acaSubnetId = networkIsolation ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-aca') : ''

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

module logAnalytics './modules/monitoring/log-analytics.bicep' = {
  name: 'log-analytics-deploy'
  params: {
    location: location
    workspaceName: lawName
    retentionInDays: logRetentionInDays
  }
}

module appInsights './modules/monitoring/app-insights.bicep' = {
  name: 'app-insights-deploy'
  params: {
    location: location
    appInsightsName: appInsightsName
    workspaceId: logAnalytics.outputs.workspaceId
  }
}

module containerEnv './modules/compute/container-env.bicep' = {
  name: 'container-env-deploy'
  params: {
    location: location
    caeName: caeName
    subnetId: acaSubnetId
    networkIsolation: networkIsolation
    logAnalyticsWorkspaceName: lawName
  }
  dependsOn: [
    logAnalytics
  ]
}

module chromadb './modules/data/chromadb.bicep' = {
  name: 'chromadb-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-chromadb-${environment}'
    storageAccountName: storageAccountName
    storageAccountKey: storageAccount.listKeys().keys[0].value
    cpu: chromaDbCpu
    memory: chromaDbMemory
  }
}

// ================= Outputs =================
output caeId string = containerEnv.outputs.caeId
output chromaDbFqdn string = chromadb.outputs.internalFqdn
output logAnalyticsWorkspaceId string = logAnalytics.outputs.workspaceId
output appInsightsConnectionString string = appInsights.outputs.connectionString
output appInsightsId string = appInsights.outputs.appInsightsId

