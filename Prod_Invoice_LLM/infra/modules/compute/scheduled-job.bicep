// ================= Scheduled Container Apps Job (cron) =================
// Gap 126: the first Microsoft.App/jobs resource in this repo. Everything under
// modules/compute/ before this was a long-running containerApp; nothing here
// could run work *on a schedule*, which is why `outbound_invoice.overdue`
// (Feature 15) had no possible trigger -- overdue is a read-time computation, so
// no request path ever produces the moment that event would fire from.
//
// Deliberately generic rather than overdue-specific: the job's identity is its
// `command` + `cronExpression`, both parameters. Adding a second scheduled
// job later (e.g. the tracker's Gap 183 Autopilot, which needs the same
// scheduler) is another `module` block in 08-apps.bicep with a different
// command/cron, not a second copy of this file.
//
// The container/env-var/Key Vault secretRef shape mirrors queue-worker.bicep --
// same user-assigned identity, same ACR pull-by-identity, same `keyVaultUrl`
// secret references -- so there is one pattern to learn for every compute
// resource in this environment.

param location string
param caeId string

@description('Name of the Container Apps job resource, e.g. caj-overdue-sweep-dev.')
param jobName string

param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

@description('Container image to run. Normally the invoice-be image: the scheduled entrypoints live in apps/invoice-be/scripts/ and ship inside it.')
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Name of the container inside the job template.')
param containerName string = 'job'

@description('Entrypoint to run on each execution, e.g. [\'python\', \'scripts/sweep_outbound_overdue.py\']. This is what makes the module reusable for a second scheduled job.')
param command array

@description('Extra arguments appended to the command, e.g. [\'--dry-run\'].')
param args array = []

@description('Cron schedule, evaluated in UTC by Container Apps. Default 02:00 UTC daily.')
param cronExpression string = '0 2 * * *'

@description('Registry the image is pulled from.')
param acrName string

// Values config.py needs at import time. DATABASE_URL/REDIS_URL/CHROMA_HOST/
// CHROMA_PORT/CLERK_SECRET_KEY/TOKEN_ENCRYPTION_KEY have no defaults in
// Settings, so a job container missing any of them fails on `import config`
// before it runs a single line of sweep logic.
param chromaHost string

@description('Azure OpenAI endpoint. Not needed by the overdue sweep itself, wired in so a future LLM-driven scheduled job needs no new plumbing.')
param azureOpenAiEndpoint string = ''

@description('Azure OpenAI deployment name. Same rationale as azureOpenAiEndpoint.')
param azureOpenAiDeploymentName string

@description('Feature 6.1 A2: fast, non-reasoning deployment for routing, summarising and narration. Empty = use azureOpenAiDeploymentName.')
param azureOpenAiFastDeploymentName string = ''

@description('Application Insights connection string. Empty by default (the overdue sweep does not emit telemetry); the golden-bank eval job needs it so scripts/run_agent_eval.py\'s track_eval_result()/emit_online_signals() calls actually reach appi-invoicellm-dev instead of silently no-op-ing to stdout.')
param appInsightsConnectionString string = ''

@description('vCPU allocation. A sweep is a few queries plus outbound HTTP -- far below the worker\'s 2.0.')
param cpu string = '0.5'

@description('Memory allocation.')
param memory string = '1.0Gi'

@description('Seconds before a stuck execution is killed. Bounds a hung outbound webhook delivery so a job replica cannot run until the next scheduled execution.')
param replicaTimeout int = 1800

@description('Retries for a failed execution. 0 because these entrypoints are idempotent and re-run on the next schedule anyway -- a retry storm against a failing dependency buys nothing.')
param replicaRetryLimit int = 0

// Feature 24 (2026-08-23): two generic escape hatches, added rather than a
// third/fourth job-specific parameter pair, because the alternative was this
// module growing an `azureSubscriptionId`, an `opsDigestWindowHours`, a
// `sendgridApiKey` and so on for every new scheduled entrypoint -- which is the
// exact copy-per-job shape the header comment says this module exists to avoid.
//
// Both default empty, and `concat()` with an empty array is the identity
// operation, so every job that does not pass them (the overdue sweep) produces
// a byte-identical template to before.
@description('Extra plain environment variables, e.g. [{ name: \'AZURE_SUBSCRIPTION_ID\', value: \'...\' }]. Appended after the standard set, so a job can also override one by re-declaring it (last wins in Container Apps).')
param extraEnv array = []

@description('Extra Key Vault secret references, e.g. [{ name: \'sendgrid-key-secret\', secretName: \'SENDGRID-API-KEY\' }]. `secretName` is the Key Vault secret name; the vault URL and the managed identity are filled in here so a caller never has to build a keyVaultUrl by hand.')
param extraSecrets array = []

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

var extraSecretRefs = [for secret in extraSecrets: {
  name: secret.name
  keyVaultUrl: '${keyVaultUrl}/secrets/${secret.secretName}'
  identity: userAssignedIdentityId
}]

resource scheduledJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: replicaTimeout
      replicaRetryLimit: replicaRetryLimit
      scheduleTriggerConfig: {
        cronExpression: cronExpression
        // One replica, one completion: these sweeps are single-process
        // batch jobs. Running two in parallel would have both read the same
        // un-notified invoices before either marked them.
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedIdentityId
        }
      ]
      secrets: concat([
        {
          name: 'db-url-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/DATABASE-URL'
          identity: userAssignedIdentityId
        }
        {
          name: 'redis-url-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/REDIS-URL'
          identity: userAssignedIdentityId
        }
        {
          name: 'clerk-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/CLERK-SECRET-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'token-encryption-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/TOKEN-ENCRYPTION-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'openai-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-OPENAI-API-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'storage-conn-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-STORAGE-CONNECTION-STRING'
          identity: userAssignedIdentityId
        }
      ], extraSecretRefs)
    }
    template: {
      containers: [
        {
          name: containerName
          image: image
          command: command
          args: args
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: concat([
            {
              name: 'DATABASE_URL'
              secretRef: 'db-url-secret'
            }
            {
              name: 'REDIS_URL'
              secretRef: 'redis-url-secret'
            }
            {
              name: 'CHROMA_HOST'
              value: chromaHost
            }
            {
              // Gap 422: 443, NOT 8000. `chromaHost` is an Azure Container Apps
              // *internal ingress* FQDN, and ACA publishes internal ingress on 80
              // (http) and 443 (https). The chromadb app's `targetPort: 8000` is
              // the port its container listens on inside the replica -- it is not
              // what the FQDN serves, so <fqdn>:8000 reaches nothing and hangs
              // until the client timeout fires, dropping the process onto an
              // empty in-container PersistentClient. This module was missed when
              // the two long-running apps were fixed, so every job built from it
              // (caj-chat-doc-ttl-dev, emit-online-signals) was still searching
              // an empty store. Matches the verified live config on
              // ca-invoice-be-dev revision --0000131.
              name: 'CHROMA_PORT'
              value: '443'
            }
            {
              // Must move together with CHROMA_PORT above -- 443 requires SSL.
              name: 'CHROMA_USE_SSL'
              value: 'true'
            }
            {
              name: 'CLERK_SECRET_KEY'
              secretRef: 'clerk-secret-secret'
            }
            {
              name: 'TOKEN_ENCRYPTION_KEY'
              secretRef: 'token-encryption-secret'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            {
              name: 'AZURE_STORAGE_CONNECTION_STRING'
              secretRef: 'storage-conn-secret'
            }
            {
              name: 'LLM_PROVIDER'
              value: 'azure'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'openai-key-secret'
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: '2024-02-15-preview'
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
              value: azureOpenAiDeploymentName
            }
            {
              name: 'AZURE_OPENAI_FAST_DEPLOYMENT_NAME'
              value: azureOpenAiFastDeploymentName
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
          ], extraEnv)
        }
      ]
    }
  }
}

output jobName string = scheduledJob.name
output jobId string = scheduledJob.id
