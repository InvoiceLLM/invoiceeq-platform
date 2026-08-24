targetScope = 'resourceGroup'

// Narrow, standalone deployment for ONE resource: the Feature 19/20 Cost +
// Health/Performance Azure Workbook (Area 1 + Area 2 combined per the
// founder's 2026-08-23 scoping decision). Not routed through
// 08-apps.bicep/09-monitoring.bicep for the same reason gpt4o-deployment.bicep
// and the deleted agent-eval-job-only.bicep weren't: this repo's known
// params.dev.json image-tag drift makes a full stage deploy risky, and this
// workbook only touches a Microsoft.Insights/workbooks resource that no
// other stage owns.
//
// Replaces 09-monitoring.bicep's `dashboard` module (Task 19.5's 6-panel
// workbook, written 2026-08-19, never actually deployed) as the live
// Feature 19/20 dashboard. That module and infra/modules/monitoring/
// dashboard.bicep are left in place rather than deleted in this pass --
// removing them is a separate, deliberate cleanup, not a side effect of
// adding this one.
//
// Every KQL query embedded in cost_health_workbook.json was run live
// against law-invoicellm-dev / this subscription via `az monitor
// log-analytics query` and `az graph query` on 2026-08-23 before this file
// was written -- see feature_20_observability_monitoring_alerts.md and
// be_features_tracker.md for the verification record.

@description('Azure region for the workbook resource. Must match the target resource group region.')
param location string = resourceGroup().location

@description('Display name shown in Azure Portal > Monitor > Workbooks.')
param workbookDisplayName string = 'Invoice AI — Cost & Health/Performance (Feature 19/20)'

@description('A stable GUID for this workbook resource name, so re-deploys update the same resource rather than creating duplicates.')
param workbookId string = '618c81c7-353d-498a-93be-becc2e3e84cf'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: 'law-invoicellm-dev'
}

resource costHealthWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: workbookId
  location: location
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    sourceId: logAnalytics.id
    serializedData: loadTextContent('./monitoring/cost_health_workbook.json')
  }
}

output workbookResourceId string = costHealthWorkbook.id
output workbookPortalUrl string = 'https://portal.azure.com/#@/resource${costHealthWorkbook.id}/workbook'
