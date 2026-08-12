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
param azureOpenAiDeploymentName string = ''

@description('vCPU allocation. A sweep is a few queries plus outbound HTTP -- far below the worker\'s 2.0.')
param cpu string = '0.5'

@description('Memory allocation.')
param memory string = '1.0Gi'

@description('Seconds before a stuck execution is killed. Bounds a hung outbound webhook delivery so a job replica cannot run until the next scheduled execution.')
param replicaTimeout int = 1800

@description('Retries for a failed execution. 0 because these entrypoints are idempotent and re-run on the next schedule anyway -- a retry storm against a failing dependency buys nothing.')
param replicaRetryLimit int = 0

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

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
      secrets: [
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
      ]
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
          env: [
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
              name: 'CHROMA_PORT'
              value: '8000'
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
          ]
        }
      ]
    }
  }
}

output jobName string = scheduledJob.name
output jobId string = scheduledJob.id
