targetScope = 'resourceGroup'

// ============ Feature 33 Task 33.16: ATLAS weekly analyst sweep job ============
//
// Why this file exists:
// Same pattern as `infra/chat-doc-ttl-job-only.bicep` and other standalone job templates.
// Deploys the Monday 06:00 UTC ATLAS analyst job over `modules/compute/scheduled-job.bicep`.
//
// What this runs: `scripts/run_weekly_analyst.py` (Feature 33, task 33.16).
// Runs the ATLAS 7-step loop across all active tenants, persists TodayItems, InputRequests,
// and refreshes tenant profile rules and routine contradict detection.
//
// Cadence: Weekly, every Monday at 06:00 UTC (`0 6 * * 1`).
//

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm`.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image. Defaults to `acrinvoicellmdev2`.')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. Any build containing scripts/run_weekly_analyst.py.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Cron (UTC). Weekly on Monday at 06:00 UTC.')
param analystWeeklyCron string = '0 6 * * 1'

@description('Seconds before the execution is killed. 3600s allows iterating across all active tenants with room for LLM analysis steps.')
param analystWeeklyReplicaTimeout int = 3600

@description('Azure OpenAI deployment name. gpt-5-mini is the primary model deployment.')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Azure OpenAI data-plane api-version (GA 2024-10-21).')
param azureOpenAiApiVersion string = '2024-10-21'

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var appInsightsName = 'appi-${namingPrefix}-${environment}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

module analystWeeklyJob './modules/compute/scheduled-job.bicep' = {
  name: 'analyst-weekly-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-analyst-weekly-${environment}'
    containerName: 'analyst-weekly'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/run_weekly_analyst.py'
    ]
    args: []
    cronExpression: analystWeeklyCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureOpenAiApiVersion: azureOpenAiApiVersion
    appInsightsConnectionString: appInsights.properties.ConnectionString
    cpu: '0.5'
    memory: '1.0Gi'
    replicaTimeout: analystWeeklyReplicaTimeout
  }
}

output jobName string = analystWeeklyJob.outputs.jobName
output jobId string = analystWeeklyJob.outputs.jobId
