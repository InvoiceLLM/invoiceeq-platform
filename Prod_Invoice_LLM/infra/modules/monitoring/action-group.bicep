param actionGroupName string
param shortName string
param emailAddress string

// Action groups are a global/regionless resource type.
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: 'global'
  properties: {
    groupShortName: shortName
    enabled: true
    emailReceivers: [
      {
        name: 'primary-email'
        emailAddress: emailAddress
        useCommonAlertSchema: true
      }
    ]
  }
}

output actionGroupId string = actionGroup.id
