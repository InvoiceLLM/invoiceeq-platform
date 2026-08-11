// Gaps 119 + 121: daily scheduled job that runs paid-plan lapse demotion and
// free-tier quota refill for idle tenants (scripts/sweep_billing_lifecycle.py).
// Reuses the invoice-be image; overrides command so entrypoint.sh / uvicorn
// does not start. Only DATABASE_URL is required for these scripts.

param location string
param caeId string
param jobName string
param userAssignedIdentityId string
param keyVaultName string
param acrName string
param image string

@description('Cron expression (UTC) for the billing lifecycle sweep. Default: daily 06:00.')
param cronExpression string = '0 6 * * *'

@description('vCPU for the job replica.')
param cpu string = '0.25'

@description('Memory for the job replica.')
param memory string = '0.5Gi'

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource billingLifecycleJob 'Microsoft.App/jobs@2024-03-01' = {
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
      replicaTimeout: 1800
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: cronExpression
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
      ]
    }
    template: {
      containers: [
        {
          name: 'billing-lifecycle-sweep'
          image: image
          // Override image CMD/entrypoint so we do not run uvicorn / alembic.
          command: [
            'python'
          ]
          args: [
            'scripts/sweep_billing_lifecycle.py'
          ]
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'db-url-secret'
            }
          ]
        }
      ]
    }
  }
}

output jobName string = billingLifecycleJob.name
output jobId string = billingLifecycleJob.id
