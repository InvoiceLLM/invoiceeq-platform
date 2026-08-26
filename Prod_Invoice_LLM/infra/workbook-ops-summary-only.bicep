targetScope = 'resourceGroup'

// Narrow, standalone deployment for ONE resource: the Ops Summary Azure
// Workbook (Gap 325, 2026-08-26). Follows the exact pattern of
// workbook-cost-health-only.bicep / workbook-ai-control-tower-only.bicep /
// rbac-monitoring-cost-only.bicep -- not routed through 08-apps.bicep/
// 09-monitoring.bicep, for the same reason those files aren't: this repo's
// known params.dev.json image-tag/naming-prefix drift makes a full stage
// deploy risky, and this workbook only touches a Microsoft.Insights/workbooks
// resource that no other stage owns.
//
// One table, one query, 4 rows, no scrolling -- founder-approved design
// (Gap 325). Cost Control / Infrastructure / AI Health read the latest
// `ops_recommendation` event per category (Gaps 318/319/322); API Health is
// live-computed straight from `AppRequests` -- that category does not exist
// in `services/ops_recommendation.py` and this workbook does not invent one
// there. This page is a one-glance summary; full detail stays on
// cost_health_workbook.json / ai_control_tower_workbook.json.
//
// The combined 4-row query and two of the "Recent Activity" derivations were
// run live against law-invoicellm-dev / this subscription via `az monitor
// log-analytics query` on 2026-08-26 before this file was written -- see
// be_features_tracker.md's Gap 325 entry for the real output.

@description('Azure region for the workbook resource. Must match the target resource group region.')
param location string = resourceGroup().location

@description('Display name shown in Azure Portal > Monitor > Workbooks.')
param workbookDisplayName string = 'Invoice AI — Ops Summary (Gap 325)'

@description('A stable GUID for this workbook resource name, so re-deploys update the same resource rather than creating duplicates.')
param workbookId string = '7107048d-2102-4882-ae14-f1e51c8bc21d'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: 'law-invoicellm-dev'
}

resource opsSummaryWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: workbookId
  location: location
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    sourceId: logAnalytics.id
    serializedData: loadTextContent('./monitoring/ops_summary_workbook.json')
  }
}

output workbookResourceId string = opsSummaryWorkbook.id
output workbookPortalUrl string = 'https://portal.azure.com/#@/resource${opsSummaryWorkbook.id}/workbook'
