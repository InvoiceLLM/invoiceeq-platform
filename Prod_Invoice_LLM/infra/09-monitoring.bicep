targetScope = 'resourceGroup'

// ================= Stage 9: Monitoring & Observability =================
// Log Analytics, Application Insights, an email action group, diagnostic
// settings wiring every resource to the workspace, and one health/
// availability alert per resource that exposes a meaningful metric
// (Cloud_Architecture_Document.md §11). Depends on Stages 1-8 all being
// deployed (it references every resource in the stack by name).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Email address to receive all cost/health alert notifications')
param alertEmail string

var lawName = 'law-${namingPrefix}-${environment}'
var appInsightsName = 'appi-${namingPrefix}-${environment}'
var actionGroupName = 'ag-${namingPrefix}-${environment}'
var backendAppName = 'ca-invoice-be-${environment}'
var workerAppName = 'ca-queue-worker-${environment}'
var frontendAppName = 'ca-invoice-fe-${environment}'
var chromaDbAppName = 'ca-chromadb-${environment}'
var postgresServerName = 'psql-${namingPrefix}-${environment}'
var redisName = 'redis-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'

module logAnalytics './modules/monitoring/log-analytics.bicep' = {
  name: 'log-analytics-deploy'
  params: {
    location: location
    workspaceName: lawName
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

module actionGroup './modules/monitoring/action-group.bicep' = {
  name: 'action-group-deploy'
  params: {
    actionGroupName: actionGroupName
    shortName: 'invllmalrt'
    emailAddress: alertEmail
  }
}

// `scope` on an extension resource must be a symbolic resource reference,
// not a resourceId()-computed string — so each diagnostic setting target
// needs its own `existing` declaration (one per literal resource type)
// rather than a single generic array-driven loop.
resource caeExisting 'Microsoft.App/managedEnvironments@2024-03-01' existing = { name: caeName }
resource backendAppExisting 'Microsoft.App/containerApps@2024-03-01' existing = { name: backendAppName }
resource workerAppExisting 'Microsoft.App/containerApps@2024-03-01' existing = { name: workerAppName }
resource frontendAppExisting 'Microsoft.App/containerApps@2024-03-01' existing = { name: frontendAppName }
resource chromaDbAppExisting 'Microsoft.App/containerApps@2024-03-01' existing = { name: chromaDbAppName }
resource postgresServerExisting 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' existing = { name: postgresServerName }
resource redisExisting 'Microsoft.Cache/redisEnterprise@2025-04-01' existing = { name: redisName }
resource storageAccountExisting 'Microsoft.Storage/storageAccounts@2023-01-01' existing = { name: storageAccountName }
resource acrExisting 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: acrName }
resource openaiExisting 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: openaiName }
resource docIntelExisting 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: docIntelName }
resource keyVaultExisting 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: keyVaultName }

var diagLogsAndMetrics = {
  logs: [
    { categoryGroup: 'allLogs', enabled: true }
  ]
  metrics: [
    { category: 'AllMetrics', enabled: true }
  ]
}

resource diagCae 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${caeName}'
  scope: caeExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagBackend 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${backendAppName}'
  scope: backendAppExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagWorker 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${workerAppName}'
  scope: workerAppExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagFrontend 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${frontendAppName}'
  scope: frontendAppExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagChromaDb 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${chromaDbAppName}'
  scope: chromaDbAppExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagPostgres 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${postgresServerName}'
  scope: postgresServerExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagRedis 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${redisName}'
  scope: redisExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
// NOTE: the top-level storage account resource only supports metrics
// diagnostics; blob/queue log categories live on the blobServices/
// queueServices sub-resources. If `allLogs` is rejected at deploy time,
// drop the `logs` block here and add per-service diagnostic settings.
resource diagStorage 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${storageAccountName}'
  scope: storageAccountExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagAcr 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${acrName}'
  scope: acrExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagOpenai 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${openaiName}'
  scope: openaiExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagDocIntel 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${docIntelName}'
  scope: docIntelExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}
resource diagKeyVault 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${keyVaultName}'
  scope: keyVaultExisting
  properties: union({ workspaceId: logAnalytics.outputs.workspaceId }, diagLogsAndMetrics)
}

module alertRules './modules/monitoring/alert-rules.bicep' = {
  name: 'alert-rules-deploy'
  params: {
    actionGroupId: actionGroup.outputs.actionGroupId
    backendAppName: backendAppName
    workerAppName: workerAppName
    frontendAppName: frontendAppName
    chromaDbAppName: chromaDbAppName
    postgresServerName: postgresServerName
    redisName: redisName
    storageAccountName: storageAccountName
    openaiName: openaiName
    docIntelName: docIntelName
    keyVaultName: keyVaultName
    caeName: caeName
  }
}

// ================= Outputs =================
output logAnalyticsWorkspaceId string = logAnalytics.outputs.workspaceId
output actionGroupId string = actionGroup.outputs.actionGroupId
output appInsightsConnectionString string = appInsights.outputs.connectionString
