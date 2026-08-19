// Health/availability alert coverage for every resource in the stack that
// exposes a meaningful metric, per Cloud_Architecture_Document.md §11.2.
// NOTE: metric names below are Microsoft's documented names as of this
// writing. Before the first real run, spot-check with:
//   az monitor metrics list-definitions --resource <resourceId> -o table
// (metric availability occasionally shifts between API/SKU versions).

param location string = 'global'
param actionGroupId string
@description('Log Analytics workspace resource id. Required for the Gap 257 log-based DLQ alert (scheduled query).')
param logAnalyticsWorkspaceId string
@description('Region for scheduledQueryRules (cannot be global). Defaults to the resource group location.')
param queryAlertLocation string = resourceGroup().location

param backendAppName string
param workerAppName string
param frontendAppName string
param chromaDbAppName string
param websiteAppName string = ''
param postgresServerName string
param redisName string
param storageAccountName string
param openaiName string
param docIntelName string
param keyVaultName string
param caeName string

var baseApps = [
  { name: backendAppName, includeHttp5xx: true }
  { name: workerAppName, includeHttp5xx: false }
  { name: frontendAppName, includeHttp5xx: false }
  { name: chromaDbAppName, includeHttp5xx: false }
]

var containerApps = !empty(websiteAppName) ? concat(baseApps, [
  { name: websiteAppName, includeHttp5xx: true }
]) : baseApps

// ---- Container Apps: restart-loop, CPU, memory (all 4 apps) ----
resource restartAlerts 'Microsoft.Insights/metricAlerts@2018-03-01' = [for app in containerApps: {
  name: 'alert-${app.name}-restart-loop'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [
      resourceId('Microsoft.App/containerApps', app.name)
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'RestartCount'
          metricName: 'RestartCount'
          operator: 'GreaterThan'
          threshold: 3
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroupId }
    ]
  }
}]

resource cpuAlerts 'Microsoft.Insights/metricAlerts@2018-03-01' = [for app in containerApps: {
  name: 'alert-${app.name}-cpu-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [
      resourceId('Microsoft.App/containerApps', app.name)
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'CpuPercentage'
          metricName: 'CpuPercentage'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroupId }
    ]
  }
}]

resource memoryAlerts 'Microsoft.Insights/metricAlerts@2018-03-01' = [for app in containerApps: {
  name: 'alert-${app.name}-memory-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [
      resourceId('Microsoft.App/containerApps', app.name)
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'MemoryPercentage'
          metricName: 'MemoryPercentage'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroupId }
    ]
  }
}]

// ---- Backend only: HTTP 5xx rate (Cloud Architecture Document §11.2) ----
resource backend5xxAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${backendAppName}-http-5xx-rate'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [
      resourceId('Microsoft.App/containerApps', backendAppName)
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'Http5xxCount'
          metricName: 'Requests'
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
          dimensions: [
            {
              name: 'statusCodeCategory'
              operator: 'Include'
              values: [ '5xx' ]
            }
          ]
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroupId }
    ]
  }
}

// ---- Website only: HTTP 5xx rate ----
resource website5xxAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (!empty(websiteAppName)) {
  name: 'alert-${websiteAppName}-http-5xx-rate'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [
      resourceId('Microsoft.App/containerApps', websiteAppName)
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'Http5xxCount'
          metricName: 'Requests'
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
          dimensions: [
            {
              name: 'statusCodeCategory'
              operator: 'Include'
              values: [ '5xx' ]
            }
          ]
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroupId }
    ]
  }
}

// ---- PostgreSQL: CPU, storage, active connections ----
resource postgresCpuAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${postgresServerName}-cpu-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.DBforPostgreSQL/flexibleServers', postgresServerName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'cpu_percent', metricName: 'cpu_percent', operator: 'GreaterThan', threshold: 80, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

resource postgresStorageAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${postgresServerName}-storage-high'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [ resourceId('Microsoft.DBforPostgreSQL/flexibleServers', postgresServerName) ]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'storage_percent', metricName: 'storage_percent', operator: 'GreaterThan', threshold: 85, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

resource postgresConnectionsAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${postgresServerName}-connections-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.DBforPostgreSQL/flexibleServers', postgresServerName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'active_connections', metricName: 'active_connections', operator: 'GreaterThan', threshold: 80, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

// ---- Redis Enterprise: server load (Cloud Architecture Document calls this "memory utilization") ----
resource redisLoadAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${redisName}-server-load-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.Cache/redisEnterprise/databases', redisName, 'default') ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'server_load', metricName: 'server_load', operator: 'GreaterThan', threshold: 80, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

// ---- Storage: availability + egress anomaly ----
resource storageAvailabilityAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${storageAccountName}-availability-low'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [ resourceId('Microsoft.Storage/storageAccounts', storageAccountName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'Availability', metricName: 'Availability', operator: 'LessThan', threshold: 100, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

resource storageEgressAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${storageAccountName}-egress-anomaly'
  location: location
  properties: {
    severity: 3
    enabled: true
    scopes: [ resourceId('Microsoft.Storage/storageAccounts', storageAccountName) ]
    evaluationFrequency: 'PT1H'
    windowSize: 'P1D' // was 'PT24H' - not a valid Azure Monitor windowSize value (max granularity is ISO 8601 with day units, not 24 hour units); this was the actual reason Stage 9 never deployed successfully (confirmed via `az deployment group what-if`)
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'Egress', metricName: 'Egress', operator: 'GreaterThan', threshold: 10737418240, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

// ---- Dead-Letter Queue (DLQ): Poison Message Alert (Sev 1) ----
// BE Gap 257: the previous Microsoft.Insights/metricAlerts rule filtered
// QueueMessageCount on a QueueName dimension. Azure Storage's QueueMessageCount
// metric has no dimensions (confirmed live via az rest on metric definitions),
// so that rule could never fire. Replaced with a log-based scheduled query over
// the same KQL the Feature 20 workbook already uses (dashboard.bicep panel:
// ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED").
// The worker emits that line in queue_worker/main_worker.py::_route_to_dead_letter_queue.
// New resource name (scheduledQueryRules, not metricAlerts) so an already-deployed
// metric alert of the old type/name is not a type-change conflict; delete
// alert-${storageAccountName}-dlq-poison-message manually if it exists.
resource dlqPoisonAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${workerAppName}-dlq-poison-isolated'
  location: queryAlertLocation
  properties: {
    displayName: 'Queue worker isolated a poison message (DLQ)'
    description: 'Fires when the queue worker logs POISON MESSAGE ISOLATED — a message failed dequeue retries and was moved to extraction-tasks-deadletter-queue. Gap 257: log-based because Storage QueueMessageCount has no QueueName dimension.'
    severity: 1
    enabled: true
    scopes: [ logAnalyticsWorkspaceId ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: true
    criteria: {
      allOf: [
        {
          query: 'ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [ actionGroupId ]
    }
  }
}

// ---- Azure OpenAI / Doc Intelligence: throttling + availability ----
resource openaiThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${openaiName}-client-errors'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.CognitiveServices/accounts', openaiName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'ClientErrors', metricName: 'ClientErrors', operator: 'GreaterThan', threshold: 5, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

resource docIntelThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${docIntelName}-client-errors'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.CognitiveServices/accounts', docIntelName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'ClientErrors', metricName: 'ClientErrors', operator: 'GreaterThan', threshold: 5, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

// ---- Key Vault: availability (flags network/RBAC misconfig making it unreachable) ----
resource keyVaultAvailabilityAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${keyVaultName}-availability-low'
  location: location
  properties: {
    severity: 1
    enabled: true
    scopes: [ resourceId('Microsoft.KeyVault/vaults', keyVaultName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'Availability', metricName: 'Availability', operator: 'LessThan', threshold: 100, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}

// ---- Container Apps Environment: Resource Health (no direct metric; an
// outage here silently takes down all 4 apps at once, so this is covered
// via the Activity Log's ResourceHealth category instead of a metric). ----
resource caeResourceHealthAlert 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: 'alert-${caeName}-resource-health'
  location: 'global'
  properties: {
    enabled: true
    scopes: [
      resourceId('Microsoft.App/managedEnvironments', caeName)
    ]
    condition: {
      allOf: [
        { field: 'category', equals: 'ResourceHealth' }
        { field: 'resourceId', equals: resourceId('Microsoft.App/managedEnvironments', caeName) }
        { field: 'properties.currentHealthStatus', equals: 'Unavailable' }
      ]
    }
    actions: {
      actionGroups: [
        { actionGroupId: actionGroupId }
      ]
    }
  }
}
