// Standalone deploy of the three sweep jobs that 08-apps.bicep declares but
// that have never been deployed: caj-overdue-sweep (Gap 126),
// caj-billing-lifecycle (Gap 126 / Gap 71) and caj-sandbox-sweep (Gap 357).
//
// Why this file exists instead of just running Stage 8. A what-if of
// 08-apps.bicep against rg-invoice-llm-dev on 2026-09-04 showed it would not
// only create these three jobs but ALSO create a second Front Door profile
// (afd-invoicellm-dev), an AFD endpoint, origin group, security policy, WAF
// policy and a customDomains binding for invoicellm.admsofttech.com --
// alongside the invoiceeq-fd-profile that already fronts the site. That is a
// DNS-affecting change nobody asked for, so Stage 8 stays un-run and the
// jobs ship through this file, the same way chat-doc-ttl-job-only.bicep and
// emit-online-signals-job-only.bicep already do.
//
// Every module argument below mirrors the corresponding block in
// 08-apps.bicep exactly, except that the shared-resource references are
// `existing` lookups rather than in-template resources. Keep the two in sync:
// if 08-apps.bicep changes a sweep job's args, change them here too.
//
// Deploy:
//   az deployment group create -g rg-invoice-llm-dev \
//     --template-file sweep-jobs-only.bicep
// (all params default to this environment's real names; nothing from
// params.dev.json is needed.)

targetScope = 'resourceGroup'

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. `invoicellm` is the prefix this environment was actually built with.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image.')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. `:latest` is retagged by CI on every dev deploy and, as of 2026-09-04, resolves to the same digest as the live ca-invoice-be-dev image.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Azure OpenAI deployment the sweep scripts would use if they ever made an LLM call (they do not; config.py reads it at import).')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Fast/non-reasoning deployment. Deliberately empty: founder decision 2026-09-04 to stay on gpt-5-mini everywhere.')
param azureOpenAiFastDeploymentName string = ''

@description('Cron (UTC) for the outbound overdue-webhook sweep. Mirrors 08-apps.bicep.')
param overdueSweepCron string = '0 2 * * *'

@description('Cron (UTC) for the sandbox-tenant reap. Mirrors 08-apps.bicep.')
param sandboxSweepCron string = '0 4 * * *'

@description('Cron (UTC) for the billing lifecycle sweep. Mirrors modules/compute/billing-lifecycle-job.bicep default.')
param billingLifecycleCron string = '0 6 * * *'

@description('vCPU for the two scheduled-job.bicep sweeps.')
param scheduledJobCpu string = '0.5'

@description('Memory for the two scheduled-job.bicep sweeps.')
param scheduledJobMemory string = '1.0Gi'

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var openAiAccountName = 'openai-${namingPrefix}-${environment}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openAiAccountName
}

module overdueSweepJob './modules/compute/scheduled-job.bicep' = {
  name: 'overdue-sweep-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-overdue-sweep-${environment}'
    containerName: 'overdue-sweep'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/sweep_outbound_overdue.py'
    ]
    cronExpression: overdueSweepCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureOpenAiFastDeploymentName: azureOpenAiFastDeploymentName
    cpu: scheduledJobCpu
    memory: scheduledJobMemory
  }
}

module sandboxSweepJob './modules/compute/scheduled-job.bicep' = {
  name: 'sandbox-sweep-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-sandbox-sweep-${environment}'
    containerName: 'sandbox-sweep'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/sweep_sandbox_tenants.py'
    ]
    cronExpression: sandboxSweepCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureOpenAiFastDeploymentName: azureOpenAiFastDeploymentName
    cpu: scheduledJobCpu
    memory: scheduledJobMemory
  }
}

// Billing runs on the shared scheduled-job module, NOT the dedicated
// modules/compute/billing-lifecycle-job.bicep. That module sets only
// DATABASE_URL, but scripts/sweep_billing_lifecycle.py imports `database` ->
// `config.settings`, and config.py requires REDIS_URL, CHROMA_HOST,
// CHROMA_PORT, CLERK_SECRET_KEY and TOKEN_ENCRYPTION_KEY at import. Proven on
// 2026-09-04: the first execution of caj-billing-lifecycle-dev died with
// `ValidationError: 6 validation errors for Settings` before reaching main().
// scheduled-job.bicep sets all of them.
module billingLifecycleJob './modules/compute/scheduled-job.bicep' = {
  name: 'billing-lifecycle-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-billing-lifecycle-${environment}'
    containerName: 'billing-lifecycle-sweep'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/sweep_billing_lifecycle.py'
    ]
    cronExpression: billingLifecycleCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureOpenAiFastDeploymentName: azureOpenAiFastDeploymentName
    cpu: '0.25'
    memory: '0.5Gi'
  }
}

output overdueSweepJobName string = overdueSweepJob.outputs.jobName
output sandboxSweepJobName string = sandboxSweepJob.outputs.jobName
