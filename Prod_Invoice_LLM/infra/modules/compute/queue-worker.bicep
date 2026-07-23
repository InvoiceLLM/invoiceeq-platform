param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
param chromaHost string
param azureOpenAiEndpoint string
param azureOpenAiDeploymentName string
param azureDocIntelEndpoint string
param acrName string
param storageAccountName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource queueWorkerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedIdentityId
        }
      ]
      ingress: null // No HTTP endpoints needed for task runner
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
          name: 'docintel-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'docintel-key-secret-2'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-KEY-2'
          identity: userAssignedIdentityId
        }
        {
          name: 'docintel-endpoint-secret-2'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-ENDPOINT-2'
          identity: userAssignedIdentityId
        }
        {
          name: 'docintel-key-secret-3'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-KEY-3'
          identity: userAssignedIdentityId
        }
        {
          name: 'docintel-endpoint-secret-3'
          keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-DOC-INTEL-ENDPOINT-3'
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
          name: 'queue-worker'
          image: image
          command: [
            'python'
            '-m'
            'queue_worker.main_worker'
          ]
          resources: {
            // Raised from 1.0/2.0Gi (Gap 41/42, Jul 2026) to support up to
            // 10 concurrent threads (main_worker.py MAX_WORKERS) holding
            // PDF bytes + OCR output + LLM responses in memory at once.
            cpu: json('2.0')
            memory: '4.0Gi'
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
              name: 'AZURE_DOC_INTEL_ENDPOINT'
              value: azureDocIntelEndpoint
            }
            {
              name: 'AZURE_DOC_INTEL_KEY'
              secretRef: 'docintel-key-secret'
            }
            {
              // Gap 41/42 scaling (Jul 2026): 2 additional Doc Intelligence
              // resources, round-robined in code (utils/doc_intel_client.py).
              // Each Key Vault secret needs its own env var - Container Apps
              // can't join multiple secretRefs into one comma-separated value.
              name: 'AZURE_DOC_INTEL_ENDPOINT_2'
              secretRef: 'docintel-endpoint-secret-2'
            }
            {
              name: 'AZURE_DOC_INTEL_KEY_2'
              secretRef: 'docintel-key-secret-2'
            }
            {
              name: 'AZURE_DOC_INTEL_ENDPOINT_3'
              secretRef: 'docintel-endpoint-secret-3'
            }
            {
              name: 'AZURE_DOC_INTEL_KEY_3'
              secretRef: 'docintel-key-secret-3'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            {
              name: 'AZURE_STORAGE_CONNECTION_STRING'
              secretRef: 'storage-conn-secret'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        // Reconciled to match the live value (Jul 2026) - this bicep
        // previously said 5 while the deployed resource was actually 10,
        // provisioned out-of-band at some point (see Gap 41 in
        // be_features_tracker.md for the drift this caused).
        maxReplicas: 10
        rules: [
          {
            // Live rule is actually named 'queue-depth-scaler', not this -
            // another sign of drift from this bicep. Renamed to match.
            name: 'queue-depth-scaler'
            custom: {
              type: 'azure-queue'
              metadata: {
                queueName: 'extraction-tasks-queue'
                accountName: storageAccountName
                // Raised from 2 (Gap 41/42, Jul 2026): each replica now
                // handles up to 10 concurrent messages (main_worker.py
                // MAX_WORKERS) instead of 1, so the old queueLength=2
                // would trigger a new replica almost immediately even
                // though a single replica has far more headroom now.
                queueLength: '15'
              }
              auth: [
                {
                  secretRef: 'storage-conn-secret'
                  triggerParameter: 'connection'
                }
              ]
            }
          }
        ]
      }
    }
  }
}
