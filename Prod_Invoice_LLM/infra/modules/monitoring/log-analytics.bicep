param location string
param workspaceName string

@description('Log retention in days. 30 is the free-tier default and enough for a dev environment.')
param retentionInDays int = 30

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
  }
}

output workspaceId string = logAnalyticsWorkspace.id
output customerId string = logAnalyticsWorkspace.properties.customerId
