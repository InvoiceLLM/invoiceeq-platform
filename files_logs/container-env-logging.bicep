param location string
param caeName string
param subnetId string
param logAnalyticsWorkspaceName string

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: logAnalyticsWorkspaceName
}

// This redeclares the same managedEnvironments resource main.bicep created
// (same name = same resource, ARM updates in place). Safe because this
// resource type only has a handful of top-level properties and we're
// specifying all of them - vnetConfiguration exactly as main.bicep set it,
// plus the new appLogsConfiguration. Nothing gets silently dropped.
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: caeName
  location: location
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: subnetId
      internal: false
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

output caeId string = containerAppsEnvironment.id
