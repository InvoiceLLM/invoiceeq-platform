param location string
param caeName string
param subnetId string

@description('Whether to provision private networking. false = Consumption CAE with Microsoft-managed networking, no VNet injection (dev); true = VNet-injected CAE (prod).')
param networkIsolation bool = false

@description('Log Analytics workspace name to wire container console/system logs to (appLogsConfiguration). Must already exist by the time this deploys -- see 06-compute-env.bicep for why the workspace is created earlier in this same stage rather than in Stage 9.')
param logAnalyticsWorkspaceName string

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: caeName
  location: location
  properties: union(
    networkIsolation ? {
      vnetConfiguration: {
        infrastructureSubnetId: subnetId
        internal: false // Set to false to allow external container app endpoints
      }
    } : {},
    {
      // Closes a real, currently-live gap (confirmed via KQL): container
      // console/system logs have not reached Log Analytics since 2026-07-15
      // because this block was never set. Shape mirrors files_logs's
      // pre-rebuild container-env-logging.bicep draft, now folded in here.
      appLogsConfiguration: {
        destination: 'log-analytics'
        logAnalyticsConfiguration: {
          customerId: logAnalyticsWorkspace.properties.customerId
          sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
        }
      }
    }
  )
}

output caeId string = containerAppsEnvironment.id
output defaultDomain string = containerAppsEnvironment.properties.defaultDomain
