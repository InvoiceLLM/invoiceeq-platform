// Azure Monitor Workbook — Single-Pane-of-Glass Operations & Observability Hub
// Feature 19 (Task 19.5): Live interactive visual dashboard for container health,
// latency heatmaps, dead-letter queue isolation, AI token burn, and error RCA.

param location string
param workbookDisplayName string = 'Invoice AI - Production Operations & Observability'
param logAnalyticsWorkspaceId string

var workbookData = {
  version: 'Notebook/1.0'
  items: [
    {
      type: 1
      content: {
        json: '# 🚀 Invoice AI SaaS — Operations & Observability Hub\nLive telemetry, container health probes, queue ingestion throughput, and AI token consumption across the platform.'
      }
      name: 'title-header'
    }
    {
      type: 3
      content: {
        version: 'KqlItem/1.0'
        query: 'ContainerAppConsoleLogs_CL | where TimeGenerated > ago(1h) | summarize TotalLogs=count(), Errors=countif(Log_s has "error" or Log_s has "Error") by ContainerAppName_s | order by Errors desc'
        size: 1
        title: '📊 1. Container Health & Error Frequency (Last 1h)'
        timeContext: {
          durationMs: 3600000
        }
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
      name: 'panel-container-health'
    }
    {
      type: 3
      content: {
        version: 'KqlItem/1.0'
        query: 'AppRequests | where TimeGenerated > ago(2h) | summarize P50_Latency_ms=percentile(DurationMs, 50), P95_Latency_ms=percentile(DurationMs, 95), P99_Latency_ms=percentile(DurationMs, 99), TotalRequests=count() by bin(TimeGenerated, 5m)'
        size: 0
        title: '⚡ 2. API Latency Heatmap (P50/P95/P99) & Request Throughput'
        timeContext: {
          durationMs: 7200000
        }
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
      name: 'panel-api-latency'
    }
    {
      type: 3
      content: {
        version: 'KqlItem/1.0'
        query: 'ContainerAppConsoleLogs_CL | where TimeGenerated > ago(24h) | where Log_s has "POISON MESSAGE ISOLATED" or Log_s has "deadletter" | project TimeGenerated, ContainerAppName_s, Log_s | order by TimeGenerated desc | take 50'
        size: 0
        title: '☠️ 3. Dead-Letter Queue (DLQ) Isolated Poison Messages'
        timeContext: {
          durationMs: 86400000
        }
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
      name: 'panel-dlq-feed'
    }
    {
      type: 3
      content: {
        version: 'KqlItem/1.0'
        query: 'AppDependencies | where TimeGenerated > ago(24h) | where Target has "openai" or Target has "cognitiveservices" | summarize TotalCalls=count(), FailedCalls=countif(Success == false), AvgDurationMs=avg(DurationMs) by Target, bin(TimeGenerated, 15m)'
        size: 0
        title: '🧠 4. Azure OpenAI & Document Intelligence Concurrency & Burn'
        timeContext: {
          durationMs: 86400000
        }
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
      name: 'panel-ai-consumption'
    }
    {
      type: 3
      content: {
        version: 'KqlItem/1.0'
        query: 'AppExceptions | where TimeGenerated > ago(24h) | summarize IncidentCount=count() by ProblemId, OuterType, OperationName | order by IncidentCount desc | take 20'
        size: 0
        title: '🚨 5. Top Application Exceptions & RCA Breakdown'
        timeContext: {
          durationMs: 86400000
        }
        queryType: 0
        resourceType: 'microsoft.operationalinsights/workspaces'
      }
      name: 'panel-top-exceptions'
    }
  ]
}

resource workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'invoice-llm-ops-workbook')
  location: location
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    sourceId: logAnalyticsWorkspaceId
    serializedData: string(workbookData)
  }
}

output workbookId string = workbook.id
