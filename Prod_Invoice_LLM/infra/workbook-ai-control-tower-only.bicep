targetScope = 'resourceGroup'

// Narrow, standalone deployment for ONE resource: the Feature 23 AI Control
// Tower workbook (Wave 5, 2026-08-24). Not routed through 08-apps.bicep/
// 09-monitoring.bicep, for the same reason workbook-cost-health-only.bicep
// and gpt4o-deployment.bicep aren't: this repo's known params.dev.json
// image-tag/naming-prefix drift (Gap 298) makes a full stage deploy risky,
// and this workbook only touches a Microsoft.Insights/workbooks resource
// that no other stage owns.
//
// One flat workbook, no tabs -- founder decision, 2026-08-24, matching
// cost_health_workbook.json's proven markdown-header + `visualization:
// "tiles"` structure exactly rather than the tabbed mechanism that caused
// repeated Workbooks bugs earlier in this feature's build (see
// be_features_tracker.md's Feature 23 Phase 2 entry).
//
// Every KQL query embedded in ai_control_tower_workbook.json was executed
// live against law-invoicellm-dev / this subscription via `az monitor
// log-analytics query` on 2026-08-24 before this file was written --
// extracted programmatically from the written JSON (not retyped) and
// re-run a second time after the file existed, 40/40 query steps, 0
// failures -- see be_features_tracker.md's Feature 23 entry and
// feature_23_ai_control_tower.md for the full verification record.

@description('Azure region for the workbook resource. Must match the target resource group region.')
param location string = resourceGroup().location

@description('Display name shown in Azure Portal > Monitor > Workbooks.')
param workbookDisplayName string = 'Invoice AI — Control Tower (Feature 23)'

@description('A stable GUID for this workbook resource name, so re-deploys update the same resource rather than creating duplicates.')
param workbookId string = 'c1168d95-73e2-49fb-8b56-5bff5cdb990a'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: 'law-invoicellm-dev'
}

resource aiControlTowerWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: workbookId
  location: location
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    sourceId: logAnalytics.id
    serializedData: loadTextContent('./monitoring/ai_control_tower_workbook.json')
  }
}

output workbookResourceId string = aiControlTowerWorkbook.id
output workbookPortalUrl string = 'https://portal.azure.com/#@/resource${aiControlTowerWorkbook.id}/workbook'
