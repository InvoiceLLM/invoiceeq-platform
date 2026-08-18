param actionGroupName string
param shortName string
param emailAddress string
param teamsWebhookUrl string = ''
param slackWebhookUrl string = ''

var teamsReceiver = !empty(teamsWebhookUrl) ? [
  {
    name: 'teams-alert-channel'
    serviceUri: teamsWebhookUrl
    useCommonAlertSchema: true
  }
] : []

var slackReceiver = !empty(slackWebhookUrl) ? [
  {
    name: 'slack-alert-channel'
    serviceUri: slackWebhookUrl
    useCommonAlertSchema: true
  }
] : []

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
    webhookReceivers: concat(teamsReceiver, slackReceiver)
  }
}

output actionGroupId string = actionGroup.id

