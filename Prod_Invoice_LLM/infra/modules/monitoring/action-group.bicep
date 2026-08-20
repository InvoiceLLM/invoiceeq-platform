// Action Groups — split by severity so critical alerts ring Teams/Slack/Email
// immediately, while informational alerts (CPU trends, throttle bursts that
// auto-scale or retry handles) go to email only without on-call pings.
//
// Critical  (Sev 0/1): email + Teams + Slack
// Info      (Sev 2/3): email only
//
// Feature 20 follow-up: alert noise reduction (2026-08-20)

param actionGroupName string   // base name; '-critical'/'-info' suffixed below
param shortName string
param emailAddress string

@description('Optional Microsoft Teams Incoming Webhook URL — critical channel only')
param teamsWebhookUrl string = ''

@description('Optional Slack Incoming Webhook URL — critical channel only')
param slackWebhookUrl string = ''

// ---- Webhook receiver arrays (only wired to the critical group) ----
var teamsReceiver = !empty(teamsWebhookUrl) ? [
  {
    name: 'teams-critical-channel'
    serviceUri: teamsWebhookUrl
    useCommonAlertSchema: true
  }
] : []

var slackReceiver = !empty(slackWebhookUrl) ? [
  {
    name: 'slack-critical-channel'
    serviceUri: slackWebhookUrl
    useCommonAlertSchema: true
  }
] : []

// ---- Critical action group: email + Teams + Slack ----
// Used for Sev 0/1 alerts that need immediate human response:
// crash-loops, 5xx storms, DLQ poison, KV outage, CAE down, storage gone.
resource criticalActionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${actionGroupName}-critical'
  location: 'global'
  properties: {
    groupShortName: '${take(shortName, 8)}Crit'
    enabled: true
    emailReceivers: [
      {
        name: 'primary-email-critical'
        emailAddress: emailAddress
        useCommonAlertSchema: true
      }
    ]
    webhookReceivers: concat(teamsReceiver, slackReceiver)
  }
}

// ---- Info action group: email only ----
// Used for Sev 2/3 alerts that are informational — CPU/memory trends,
// connection counts, throttle bursts — where auto-scale or retry will
// already be handling the situation. No Teams/Slack ping to avoid noise.
resource infoActionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${actionGroupName}-info'
  location: 'global'
  properties: {
    groupShortName: '${take(shortName, 8)}Info'
    enabled: true
    emailReceivers: [
      {
        name: 'primary-email-info'
        emailAddress: emailAddress
        useCommonAlertSchema: true
      }
    ]
    webhookReceivers: [] // intentionally empty — info alerts are email-only
  }
}

output criticalActionGroupId string = criticalActionGroup.id
output infoActionGroupId string = infoActionGroup.id

// Legacy output kept so any existing references don't silently lose alerts.
output actionGroupId string = criticalActionGroup.id
