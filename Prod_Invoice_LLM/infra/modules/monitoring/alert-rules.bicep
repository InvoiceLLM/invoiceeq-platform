// Health/availability alert coverage for every resource in the stack that
// exposes a meaningful metric, per Cloud_Architecture_Document.md §11.2.
// NOTE: metric names below are Microsoft's documented names as of this
// writing. Before the first real run, spot-check with:
//   az monitor metrics list-definitions --resource <resourceId> -o table
// (metric availability occasionally shifts between API/SKU versions).

param location string = 'global'

// ---- Dual action groups (Feature 20 noise-reduction, 2026-08-20) ----
// criticalActionGroupId → Sev 0/1: email + Teams + Slack (immediate on-call)
// infoActionGroupId    → Sev 2/3: email only (trends, informational)
param criticalActionGroupId string
param infoActionGroupId string

@description('Log Analytics workspace resource id. Required for the Gap 257 log-based DLQ alert.')
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

// ---- Environment-aware thresholds ----
// Override in params.dev.json (relaxed) / params.prod.json (tighter).
@description('Restarts in 5m before alerting. Dev: 5 (cold-start noise), Prod: 3 (real user impact).')
param restartLoopThreshold int = 5

@description('CPU % sustained 15m before alerting. Auto-scale fires at 70% so 90% = auto-scale failed.')
param cpuAlertThreshold int = 90

@description('Memory % sustained 15m before alerting.')
param memoryAlertThreshold int = 85

@description('HTTP 5xx count in 5m before alerting. Dev: 10, Prod: 5.')
param http5xxThreshold int = 10

@description('Active Postgres connections before alerting. ~80% of max_connections. Dev B-series: 340, Prod D2ds_v5: 800.')
param postgresConnectionsThreshold int = 340

@description('Storage egress bytes/day anomaly threshold. Dev: 200MB (200000000). Prod: 5GB (5000000000).')
param storageEgressThresholdBytes int = 200000000

@description('OpenAI/DocIntel client errors in 10m before alerting. Dev: 15, Prod: 10.')
param aiClientErrorThreshold int = 15

// ---- Gap 301: per-app max-replica ceilings ----
// The CPU/memory alerts below now require Replicas == maxReplicas as a second
// AllOf criterion, so they only fire once autoscale (Gap 290, also 85%
// threshold) has genuinely maxed out and is still insufficient -- not while
// autoscale is correctly handling load but just hasn't caught up yet within
// the 15m averaging window. Each value must match the corresponding
// maxReplicas default/override in 08-apps.bicep (backendMaxReplicas /
// workerMaxReplicas / frontendMaxReplicas / websiteMaxReplicas) and
// modules/data/chromadb.bicep (maxReplicas); nothing enforces that match
// automatically since this stage (09-monitoring.bicep) deploys independently
// of Stage 8, so keep them in sync by hand if either changes.
@description('Backend Container App configured max replica count (Gap 301). Must match 08-apps.bicep backendMaxReplicas.')
param backendMaxReplicas int = 5

@description('Queue-worker Container App configured max replica count (Gap 301). Must match 08-apps.bicep workerMaxReplicas.')
param workerMaxReplicas int = 10

@description('Frontend Container App configured max replica count (Gap 301). Must match 08-apps.bicep frontendMaxReplicas.')
param frontendMaxReplicas int = 2

@description('ChromaDB Container App configured max replica count (Gap 301). Must match modules/data/chromadb.bicep maxReplicas. Default 1 -- ChromaDB does not autoscale, so its CPU/memory alerts stay effectively single-condition (Replicas is always at this ceiling).')
param chromaDbMaxReplicas int = 1

@description('Website Container App configured max replica count (Gap 301). Must match 08-apps.bicep websiteMaxReplicas. Ignored when websiteAppName is empty.')
param websiteMaxReplicas int = 3

var baseApps = [
  { name: backendAppName, includeHttp5xx: true, maxReplicas: backendMaxReplicas }
  { name: workerAppName, includeHttp5xx: false, maxReplicas: workerMaxReplicas }
  { name: frontendAppName, includeHttp5xx: false, maxReplicas: frontendMaxReplicas }
  { name: chromaDbAppName, includeHttp5xx: false, maxReplicas: chromaDbMaxReplicas }
]

var containerApps = !empty(websiteAppName) ? concat(baseApps, [
  { name: websiteAppName, includeHttp5xx: true, maxReplicas: websiteMaxReplicas }
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
          threshold: restartLoopThreshold  // 5 dev / 3 prod — raised from 3 to avoid cold-start noise
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: criticalActionGroupId }  // crash-loops are always critical
    ]
  }
}]

// CPU: auto-scale fires at 70% — alert at 90% sustained 15m means auto-scale
// had 3+ eval windows to respond and didn't. Info channel (email only).
// Gap 301: AllOf now requires a second criterion -- Replicas >= this app's
// maxReplicas -- so the alert only fires once autoscale (Gap 290) has
// genuinely hit its configured ceiling and CPU is still over threshold, not
// while autoscale is correctly handling the load and just hasn't caught up
// yet within the 15m window.
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
    windowSize: 'PT15M'  // extended from PT5M: allow auto-scale to stabilize first
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'CpuPercentage'
          metricName: 'CpuPercentage'
          operator: 'GreaterThan'
          threshold: cpuAlertThreshold  // 90% (was 80%)
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
        {
          name: 'ReplicasAtMax'
          metricName: 'Replicas'
          operator: 'GreaterThanOrEqual'
          threshold: app.maxReplicas  // Gap 301: only alert once autoscale is genuinely maxed out
          timeAggregation: 'Maximum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: infoActionGroupId }  // email only — auto-scale handles transient spikes
    ]
  }
}]

// Memory: PDF extraction spikes memory for ~2 min then drops. Window PT15M
// filters out transient extraction bursts. Info channel (email only).
// Gap 301: same AllOf compound criterion as cpuAlerts above -- Replicas must
// also be at this app's maxReplicas ceiling before the alert fires.
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
    windowSize: 'PT15M'  // extended: PDF extraction spikes memory for ~2 min, not 15
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'MemoryPercentage'
          metricName: 'MemoryPercentage'
          operator: 'GreaterThan'
          threshold: memoryAlertThreshold  // 85% (was 80%)
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
        {
          name: 'ReplicasAtMax'
          metricName: 'Replicas'
          operator: 'GreaterThanOrEqual'
          threshold: app.maxReplicas  // Gap 301: only alert once autoscale is genuinely maxed out
          timeAggregation: 'Maximum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: infoActionGroupId }  // email only — transient extraction bursts
    ]
  }
}]

// 5xx storms are critical — real users failing. Threshold raised 5→param
// (10 dev / 5 prod) to filter single-user bad-request noise.
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
          threshold: http5xxThreshold  // 10 dev / 5 prod
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
      { actionGroupId: criticalActionGroupId }
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
          threshold: http5xxThreshold
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
      { actionGroupId: criticalActionGroupId }
    ]
  }
}

// ---- PostgreSQL: CPU, storage, active connections ----
// CPU: info channel, 85% threshold, PT15M window
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
        { name: 'cpu_percent', metricName: 'cpu_percent', operator: 'GreaterThan', threshold: 85, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// Storage: critical — can't auto-expand, needs manual disk increase
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
    actions: [ { actionGroupId: criticalActionGroupId } ]
  }
}

// Connections: threshold=param (~80% of max_connections for SKU).
// Window PT10M avoids PgBouncer idle-session spikes triggering noise.
resource postgresConnectionsAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${postgresServerName}-connections-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.DBforPostgreSQL/flexibleServers', postgresServerName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'  // extended: PgBouncer idle sessions can briefly spike
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'active_connections', metricName: 'active_connections', operator: 'GreaterThan', threshold: postgresConnectionsThreshold, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// ---- Redis Enterprise: server load ----
// Chat-session cache bursts are transient. 85% sustained 15m = genuine saturation.
resource redisLoadAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${redisName}-server-load-high'
  location: location
  properties: {
    severity: 2
    enabled: true
    scopes: [ resourceId('Microsoft.Cache/redisEnterprise/databases', redisName, 'default') ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'  // extended: transient bursts resolve quickly
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'server_load', metricName: 'server_load', operator: 'GreaterThan', threshold: 85, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// ---- Storage: availability + egress anomaly ----
// Availability: Azure SLA is 99.9% so <100% guarantees daily noise.
// Raised to <99% sustained PT15M. Downgraded Sev 1→2 (email only).
resource storageAvailabilityAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${storageAccountName}-availability-low'
  location: location
  properties: {
    severity: 2  // downgraded: sustained availability is serious but not on-call-worthy
    enabled: true
    scopes: [ resourceId('Microsoft.Storage/storageAccounts', storageAccountName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'  // extended: Azure SLA blips resolve in seconds
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'Availability', metricName: 'Availability', operator: 'LessThan', threshold: 99, timeAggregation: 'Average', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// Egress: parameterized threshold. Dev=200MB/day (12× normal ~17MB queue-polling).
// Prod=5GB/day. Catches runaway loops or data exfiltration.
resource storageEgressAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${storageAccountName}-egress-anomaly'
  location: location
  properties: {
    severity: 3
    enabled: true
    scopes: [ resourceId('Microsoft.Storage/storageAccounts', storageAccountName) ]
    evaluationFrequency: 'PT1H'
    windowSize: 'P1D' // P1D not PT24H — Azure Monitor requires ISO 8601 day units
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'Egress', metricName: 'Egress', operator: 'GreaterThan', threshold: storageEgressThresholdBytes, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// ---- Dead-Letter Queue (DLQ): Poison Message Alert (Sev 1) ----
// BE Gap 257: the previous Microsoft.Insights/metricAlerts rule filtered
// QueueMessageCount on a QueueName dimension. Azure Storage's QueueMessageCount
// metric has no dimensions (confirmed live via az rest on metric definitions),
// so that rule could never fire. Replaced with a log-based scheduled query over
// the same KQL the Feature 20 workbook already uses (the panel was
// ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED", from
// the since-deleted dashboard.bicep; the live workbook is
// infra/monitoring/cost_health_workbook.json).
// The worker emits that line in queue_worker/main_worker.py::_route_to_dead_letter_queue.
// New resource name (scheduledQueryRules, not metricAlerts) so an already-deployed
// metric alert of the old type/name is not a type-change conflict; delete
// alert-${storageAccountName}-dlq-poison-message manually if it exists.
resource dlqPoisonAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${workerAppName}-dlq-poison-isolated'
  location: queryAlertLocation
  properties: {
    displayName: 'Queue worker isolated a poison message (DLQ)'
    description: 'Fires when the queue worker logs POISON MESSAGE ISOLATED. Gap 257: log-based because Storage QueueMessageCount has no QueueName dimension.'
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
      actionGroups: [ criticalActionGroupId ]  // data loss risk — always critical
    }
  }
}

// ---- Azure OpenAI / Doc Intelligence: throttling ----
// Throttling is transient — LLM client retries handle it.
// Raised 5→15, window PT5M→PT10M, downgraded Sev 2→3. Email only.
resource openaiThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${openaiName}-client-errors'
  location: location
  properties: {
    severity: 3  // downgraded: throttle bursts are transient
    enabled: true
    scopes: [ resourceId('Microsoft.CognitiveServices/accounts', openaiName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'  // extended: retry storms clear quickly
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'ClientErrors', metricName: 'ClientErrors', operator: 'GreaterThan', threshold: aiClientErrorThreshold, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

resource docIntelThrottleAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${docIntelName}-client-errors'
  location: location
  properties: {
    severity: 3  // downgraded: throttle during concurrent extraction is normal
    enabled: true
    scopes: [ resourceId('Microsoft.CognitiveServices/accounts', docIntelName) ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        { name: 'ClientErrors', metricName: 'ClientErrors', operator: 'GreaterThan', threshold: aiClientErrorThreshold, timeAggregation: 'Total', criterionType: 'StaticThresholdCriterion' }
      ]
    }
    actions: [ { actionGroupId: infoActionGroupId } ]
  }
}

// ---- Key Vault: availability — always critical, no grace period ----
// KV down = all secrets unreachable = total platform outage.
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
    actions: [ { actionGroupId: criticalActionGroupId } ]
  }
}

// ---- Container Apps Environment: Resource Health ----
// CAE down = all 5 apps dead simultaneously. Always critical.
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
        { actionGroupId: criticalActionGroupId }
      ]
    }
  }
}
