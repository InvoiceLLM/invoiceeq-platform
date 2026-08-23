targetScope = 'resourceGroup'

// ============ Feature 24: the Ops Digest Agent job, and nothing else ============
//
// Why this file exists instead of just deploying Stage 8
// -------------------------------------------------------
// `08-apps.bicep` already declares this job (module `opsDigestJob`) and that is
// the canonical declaration — it is what a clean environment build produces.
// But a Stage 8 deploy against the *current* dev environment is not a safe way
// to create it. Measured with `az deployment group what-if` on 2026-08-23, that
// deploy reports **3 to create, 4 to modify**, and the 4 modifications are every
// running container app:
//
//   * `params.dev.json`'s `backendImage` is `acrinvoicellmdev.azurecr.io/
//     invoice-be:latest`. That registry **does not exist** — `az acr list`
//     returns exactly one registry, `acrinvoicellmdev2`. The live apps run
//     `acrinvoicellmdev2.azurecr.io/invoice-be:f8abe779…`, so a Stage 8 deploy
//     would repoint all four apps at an unreachable image.
//   * `params.dev.json` sets `namingPrefix: "invoice-llm"`, but this environment
//     was actually built with `invoicellm` (live: `kv-invoicellm-dev`,
//     `id-invoicellm-dev`, `cae-invoicellm-dev`). With the file's own prefix,
//     what-if rewrites every Key Vault secret URI and the user-assigned identity
//     to names that do not exist.
//   * It would also roll back Gap 290's CPU/memory scale rules, which were
//     applied live via `az containerapp update`, never through this template.
//
// So this file does what the founder already did once for Feature 23's eval job
// (`infra/agent-eval-job-only.bicep`, recorded in the tracker on 2026-08-22 as a
// "narrow, standalone bicep file"): deploy the one new resource, over the same
// shared `modules/compute/scheduled-job.bicep`, with defaults that match what is
// **actually deployed** rather than what `params.dev.json` claims.
//
// This template creates exactly one resource and modifies none.
//
//   az deployment group what-if --resource-group rg-invoice-llm-dev \
//     --template-file infra/ops-digest-job-only.bicep
//   az deployment group create   --resource-group rg-invoice-llm-dev \
//     --template-file infra/ops-digest-job-only.bicep
//
// **Prerequisite that is not optional**: the backend image must already contain
// `scripts/ops_digest_job.py`. It does not today — the Feature 24 code is
// uncommitted, so no CI build has pushed it. Deploying before that produces a
// job whose every execution fails with `No such file or directory`.
//
// Second prerequisite: `Monitoring Reader` for `id-invoicellm-dev`
// (`modules/security/rbac-assignments.bicep`, declared 2026-08-23, not
// deployed). Without it the job runs but collects zero alerts and cannot read
// the action group, so it delivers nowhere. `scripts/ops_digest_job.py
// --print-channel` inside the container is the one-command check for this.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm` — the prefix this environment was ACTUALLY built with — not params.dev.json\'s `invoice-llm`, which resolves to Key Vault/identity/CAE names that do not exist here.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image. Defaults to the one registry that exists (`acrinvoicellmdev2`); params.dev.json still names `acrinvoicellmdev`, which does not.')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. Must be a build that contains scripts/ops_digest_job.py.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Azure OpenAI deployment used for the digest synthesis call.')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Cron (UTC). Every six hours — 01:00/07:00/13:00/19:00 UTC = 06:30/12:30/18:30/00:30 IST. Kept identical to 08-apps.bicep\'s opsDigestCron; the two must not drift.')
param opsDigestCron string = '0 1,7,13,19 * * *'

@description('auto | teams | email | none. `none` renders and records the digest without sending it — the right setting for a first deploy, since the Teams webhook payload has never been delivered end to end.')
@allowed([
  'auto'
  'teams'
  'email'
  'none'
])
param opsDigestDelivery string = 'auto'

@description('SendGrid authenticated sending domain, for the email half of the critical channel.')
param sendgridSendingDomain string = ''

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
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

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

// Identical parameter set to 08-apps.bicep's `opsDigestJob` module. If one is
// edited, the other must be — they describe the same resource, and Container
// Apps will happily let a later Stage 8 deploy overwrite whatever this created.
module opsDigestJob './modules/compute/scheduled-job.bicep' = {
  name: 'ops-digest-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-ops-digest-${environment}'
    containerName: 'ops-digest'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/ops_digest_job.py'
    ]
    cronExpression: opsDigestCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    appInsightsConnectionString: appInsights.properties.ConnectionString
    replicaTimeout: 600
    extraSecrets: [
      {
        name: 'sendgrid-key-secret'
        secretName: 'SENDGRID-API-KEY'
      }
    ]
    extraEnv: [
      {
        name: 'AZURE_SUBSCRIPTION_ID'
        value: subscription().subscriptionId
      }
      {
        name: 'AZURE_COST_RESOURCE_GROUP'
        value: resourceGroup().name
      }
      {
        name: 'SENDGRID_API_KEY'
        secretRef: 'sendgrid-key-secret'
      }
      {
        name: 'SENDGRID_SENDING_DOMAIN'
        value: sendgridSendingDomain
      }
      {
        name: 'OPS_DIGEST_WINDOW_HOURS'
        value: '6'
      }
      {
        name: 'OPS_DIGEST_DELIVERY'
        value: opsDigestDelivery
      }
    ]
  }
}

output jobName string = opsDigestJob.outputs.jobName
output jobId string = opsDigestJob.outputs.jobId
