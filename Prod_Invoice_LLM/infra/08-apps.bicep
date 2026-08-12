targetScope = 'resourceGroup'

// ================= Stage 8: Application Container Apps =================
// Backend, queue-worker, frontend. Depends on Stage 6 (CAE + ChromaDB)
// and Stage 7 (RBAC — so the identity can actually pull images / read
// secrets by the time these apps start). All cross-stage values (CAE id,
// ChromaDB FQDN, identity IDs, OpenAI/DocIntel endpoints) are read via
// `existing` resource references instead of being threaded through the
// orchestrator script as deployment outputs.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Clerk SSO Publishable Client Key')
param nextPublicClerkPublishableKey string

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Image tag for backend API container')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for queue worker container')
param queueWorkerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for frontend container')
param frontendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for website container')
param websiteImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Clerk JWT issuer URL (public) -- see invoice-be.bicep for why this is not a secret')
param clerkJwtIssuer string = ''

@description('Clerk JWKS endpoint URL (public)')
param clerkJwksUrl string = ''

@description('Our company Google Cloud OAuth Client ID (connectors: Drive) -- public value, see invoice-be.bicep')
param googleClientId string = ''

@description('Our company Salesforce Connected App Consumer Key (connectors) -- public value, see invoice-be.bicep')
param salesforceClientId string = ''

@description('SendGrid-authenticated sending domain for outbound mail (Gap 125) -- public value, see invoice-be.bicep and feature_9_connectors.md. The API key/inbound webhook secret are seeded separately in Stage 5 (05-secrets.bicep), not threaded through this file.')
param sendgridSendingDomain string = ''

@description('PayU mode for invoice-be (Feature 11). test|live. Merchant key/salt are seeded in Stage 5 Key Vault, not here.')
param payuMode string = 'test'

@description('Number of Document Intelligence resources deployed (must match Stage 4/5). Threaded into queue-worker.bicep so it only wires up the docintel-2/-3 Key Vault secretRefs that Stage 5 actually seeded.')
@minValue(1)
@maxValue(3)
param docIntelInstanceCount int = 1

@description('Name of the shared ACR registry this environment pulls images from. Defaults to this environment\'s own computed name (dev, which owns it); prod must set this explicitly -- see 03-data.bicep.')
param sharedAcrName string = 'acr${replace(namingPrefix, '-', '')}${environment}'

@description('Backend Container App vCPU allocation.')
param backendCpu string = '1.0'
@description('Backend Container App memory allocation.')
param backendMemory string = '2.0Gi'
@description('Backend Container App minimum replica count.')
param backendMinReplicas int = 1
@description('Backend Container App maximum replica count.')
param backendMaxReplicas int = 5

@description('Queue-worker Container App vCPU allocation.')
param workerCpu string = '2.0'
@description('Queue-worker Container App memory allocation.')
param workerMemory string = '4.0Gi'
@description('Queue-worker Container App minimum replica count.')
param workerMinReplicas int = 1
@description('Queue-worker Container App maximum replica count.')
param workerMaxReplicas int = 10
@description('Queue-worker KEDA queue-length scale trigger threshold.')
param workerQueueScaleLength string = '15'

@description('Frontend Container App vCPU allocation.')
param frontendCpu string = '0.5'
@description('Frontend Container App memory allocation.')
param frontendMemory string = '1.0Gi'
@description('Frontend Container App minimum replica count.')
param frontendMinReplicas int = 1
@description('Frontend Container App maximum replica count.')
param frontendMaxReplicas int = 2

// Gap 126: scheduled work. Kept as its own knob set (not folded into the
// backend's) because a job's schedule is the thing most likely to be tuned per
// environment -- e.g. a prod run at a quieter hour, or a dev run left disabled.
@description('Cron schedule (UTC) for the outbound overdue-webhook sweep. Daily at 02:00 UTC by default -- after any given business day has ended in the tenant time zones this product currently serves, so an invoice due "today" is not notified while today is still in progress somewhere.')
param overdueSweepCron string = '0 2 * * *'

@description('vCPU allocation for scheduled jobs.')
param scheduledJobCpu string = '0.5'

@description('Memory allocation for scheduled jobs.')
param scheduledJobMemory string = '1.0Gi'

@description('Website Container App vCPU allocation.')
param websiteCpu string = '0.5'
@description('Website Container App memory allocation.')
param websiteMemory string = '1.0Gi'
@description('Website Container App minimum replica count. Dev default 0 (scale-to-zero); prod should set >=1 to avoid cold-starts on the public entry point.')
param websiteMinReplicas int = 1
@description('Website Container App maximum replica count.')
param websiteMaxReplicas int = 3

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'

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
  name: openaiName
}

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName
}

// FE/website FQDNs, computed rather than read from backendApp/frontendApp
// module outputs. Container App FQDNs are `<app-name>.<cae-default-domain>`,
// and the CAE (an `existing` reference, already deployed by an earlier stage)
// exposes that domain directly -- so both names are knowable before either
// app deploys. This matters because backendApp needs the FE/website origins
// for ALLOWED_ORIGINS, and frontendApp needs backendApp's fqdn for
// BACKEND_API_URL -- a real circular dependency if either side tried to read
// the other's module output instead.
var frontendFqdn = 'ca-invoice-fe-${environment}.${cae.properties.defaultDomain}'
var websiteFqdn = 'ca-invoice-website-${environment}.${cae.properties.defaultDomain}'

// OAuth redirect URIs must be the public origin (website), not the backend or internal frontend --
// backendApp and frontendApp are both internal-only (external:false), so Google/Salesforce
// redirect the browser back to the website, which proxies it to the frontend container.
var googleRedirectUri = 'https://${websiteFqdn}/api/connectors/callback/google_drive'
var salesforceRedirectUri = 'https://${websiteFqdn}/api/connectors/callback/salesforce'

module backendApp './modules/compute/invoice-be.bicep' = {
  name: 'backend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-be-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: sharedAcrName
    image: backendImage
    clerkJwtIssuer: clerkJwtIssuer
    clerkJwksUrl: clerkJwksUrl
    allowedOrigins: 'https://${frontendFqdn},https://${websiteFqdn}'
    googleClientId: googleClientId
    googleRedirectUri: googleRedirectUri
    salesforceClientId: salesforceClientId
    salesforceRedirectUri: salesforceRedirectUri
    sendgridSendingDomain: sendgridSendingDomain
    payuMode: payuMode
    backendPublicUrl: 'https://${websiteFqdn}'
    publicAppUrl: 'https://${websiteFqdn}'
    // Post-Multi-Zone: browser never reaches FE (ingress external:false). Any
    // full-page RedirectResponse (e.g. connectors oauth_callback) must land on
    // the public website origin, which proxies /settings/* to FE.
    frontendUrl: 'https://${websiteFqdn}'
    cpu: backendCpu
    memory: backendMemory
    minReplicas: backendMinReplicas
    maxReplicas: backendMaxReplicas
  }
}

// Gaps 119 + 121: daily billing lifecycle sweep (paid lapse + free quota refill).
// Same backend image as ca-invoice-be; command overridden to the sweep script.
module billingLifecycleJob './modules/compute/billing-lifecycle-job.bicep' = {
  name: 'billing-lifecycle-job-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-billing-lifecycle-${environment}'
    userAssignedIdentityId: identity.id
    keyVaultName: keyVaultName
    acrName: sharedAcrName
    image: backendImage
  }
}

module queueWorker './modules/compute/queue-worker.bicep' = {
  name: 'worker-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-queue-worker-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: sharedAcrName
    storageAccountName: storageAccountName
    image: queueWorkerImage
    docIntelInstanceCount: docIntelInstanceCount
    // Gap 180: same company OAuth apps as invoice-be — worker needs them to
    // download Drive/Salesforce files and refresh tokens during import.
    googleClientId: googleClientId
    salesforceClientId: salesforceClientId
    cpu: workerCpu
    memory: workerMemory
    minReplicas: workerMinReplicas
    maxReplicas: workerMaxReplicas
    queueScaleLength: workerQueueScaleLength
  }
}

module frontendApp './modules/compute/invoice-fe.bicep' = {
  name: 'frontend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-fe-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    backendApiUrl: backendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    acrName: sharedAcrName
    image: frontendImage
    cpu: frontendCpu
    memory: frontendMemory
    minReplicas: frontendMinReplicas
    maxReplicas: frontendMaxReplicas
  }
}

module websiteApp './modules/compute/invoice-website.bicep' = {
  name: 'website-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-website-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    backendApiUrl: backendApp.outputs.fqdn
    frontendApiUrl: frontendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    acrName: sharedAcrName
    image: websiteImage
    cpu: websiteCpu
    memory: websiteMemory
    minReplicas: websiteMinReplicas
    maxReplicas: websiteMaxReplicas
  }
}

// Gap 126: the outbound overdue-webhook sweep, and the first scheduled job in
// this environment. Runs the invoice-be image (that is where
// scripts/sweep_outbound_overdue.py ships) with a cron trigger instead of an
// HTTP/queue one -- `outbound_invoice.overdue` is derived from a date passing,
// so nothing in the request path could ever have fired it.
//
// It reuses `backendImage` rather than taking an image param of its own so the
// job always runs the same backend build as ca-invoice-be. Note that
// .github/workflows/_deploy-service.yml updates *container apps* only
// (`az containerapp update`), so on a CI push this job keeps whatever image
// reference this template last set. With the `:latest` tag used by
// params.dev.json that still resolves to the newest pushed backend image at
// execution time, since a job pulls the image when it starts a replica.
module overdueSweepJob './modules/compute/scheduled-job.bicep' = {
  name: 'overdue-sweep-job-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-overdue-sweep-${environment}'
    containerName: 'overdue-sweep'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: sharedAcrName
    image: backendImage
    command: [
      'python'
      'scripts/sweep_outbound_overdue.py'
    ]
    cronExpression: overdueSweepCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    cpu: scheduledJobCpu
    memory: scheduledJobMemory
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
output websiteUrl string = websiteApp.outputs.fqdn
