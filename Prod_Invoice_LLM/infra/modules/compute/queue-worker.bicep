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

@description('Feature 6.1 A2: fast, non-reasoning deployment for routing, summarising and narration. Empty = use azureOpenAiDeploymentName.')
param azureOpenAiFastDeploymentName string = ''
param azureDocIntelEndpoint string
param acrName string
param storageAccountName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Application Insights Connection String for OpenTelemetry APM tracing')
param appInsightsConnectionString string = ''

@description('vCPU allocation, e.g. \'2.0\'.')
param cpu string = '2.0'

@description('Memory allocation, e.g. \'4.0Gi\'.')
param memory string = '4.0Gi'

@description('Minimum replica count.')
param minReplicas int = 0

@description('Maximum replica count.')
param maxReplicas int = 10

@description('KEDA queue-length scale trigger threshold.')
param queueScaleLength string = '15'

@description('Number of Document Intelligence resources deployed (must match Stage 4/5). Gates whether the DOC-INTEL-KEY-2/3 and DOC-INTEL-ENDPOINT-2/3 Key Vault secretRefs are wired in -- those Key Vault secrets only exist when docIntelInstanceCount >= 2/3 (see 05-secrets.bicep), so referencing them unconditionally would fail deployment in dev (docIntelInstanceCount=1).')
@minValue(1)
@maxValue(3)
param docIntelInstanceCount int = 1

// Gap 180: worker downloads connector files + refreshes OAuth tokens. Without
// these, has_real_credentials() is false and Drive imports silently upload a
// stub PDF that Doc Intelligence rejects (InvalidContent). Redirect URIs are
// not needed here — only the BE oauth_callback uses them.
@description('Our company Google Cloud OAuth Client ID (connectors: Drive)')
param googleClientId string = ''

@description('Our company Salesforce Connected App Consumer Key (connectors)')
param salesforceClientId string = ''

// Gap 124/125 (email notifications) never reached this file -- the worker is
// what actually calls services/staff_notify.py's notify_processing_complete()/
// notify_auditor_action(), but with none of these params or the SendGrid
// API key, sendgrid_configured() returns false and every notification
// silently no-ops (soft-skip by design, no error). Params mirror
// invoice-be.bicep exactly; INBOUND_PARSE_SHARED_SECRET is deliberately not
// mirrored here -- only the API validates the inbound webhook, the worker
// never receives that request.
@description('SendGrid-authenticated domain used as the technical From for outbound mail -- see invoice-be.bicep')
param sendgridSendingDomain string = ''

@description('Full From address for outbound emails -- see invoice-be.bicep')
param sendgridFromEmail string = ''

@description('Display name for outbound emails -- see invoice-be.bicep')
param sendgridFromName string = 'InvoiceLLM'

@description('Inbound mail domain (MX target for SendGrid Inbound Parse) -- see invoice-be.bicep')
param emailAppDomain string = ''

@description('Platform-wide mailbox address tenants send invoices to -- see invoice-be.bicep')
param emailAppAddress string = ''

@description('Support / ops alert destination inbox -- see invoice-be.bicep')
param supportNotifyEmail string = ''

@description('Feature 27 — generic (non-invoice) extraction. Gates the classifier node in the extraction graph; with it off `doc_type` is always None and no `documents` row is ever created. Opt in per environment, exactly like enableProductionQualityJudge above.')
param enableGenericExtraction bool = false

@description('Feature 26 Part 2 — the attached-document intent split and content branch. With it off an attachment turn is Part 1\'s deterministic comparison path, byte-identical to Gap 366. NOT a gate on attachments as such (B11 item 1: `attachment_id` presence is the routing switch and is not a flag).')
param enableGenericDocChat bool = false

@description('Feature 26 E-5 / task H7 — route an attachment chat turn through the Redis-backed async queue instead of answering it synchronously. REQUIRES a reachable REDIS_URL: `services/chat_queue.py::get_redis_client()` returns None when it is empty, so enabling this without Redis enqueues into nothing. Declared here for documentation and later rollout; dev has no Redis deployed as of 2026-09-03, so it stays false.')
param enableAsyncChatQueue bool = false

@description('Feature 6.1 A3: stream phrasing calls as progress events. Off = .invoke().')
param enableChatStreaming bool = false

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

var baseSecrets = [
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
    name: 'storage-conn-secret'
    keyVaultUrl: '${keyVaultUrl}/secrets/AZURE-STORAGE-CONNECTION-STRING'
    identity: userAssignedIdentityId
  }
  {
    name: 'google-client-secret-secret'
    keyVaultUrl: '${keyVaultUrl}/secrets/GOOGLE-CLIENT-SECRET'
    identity: userAssignedIdentityId
  }
  {
    name: 'salesforce-client-secret-secret'
    keyVaultUrl: '${keyVaultUrl}/secrets/SALESFORCE-CLIENT-SECRET'
    identity: userAssignedIdentityId
  }
  // Secret name kept as 'sendgrid-key-secret' to match invoice-be.bicep's
  // existing reference to the same live Key Vault secret.
  {
    name: 'sendgrid-key-secret'
    keyVaultUrl: '${keyVaultUrl}/secrets/SENDGRID-API-KEY'
    identity: userAssignedIdentityId
  }
]

var docIntel2Secrets = docIntelInstanceCount >= 2 ? [
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
] : []

var docIntel3Secrets = docIntelInstanceCount >= 3 ? [
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
] : []

var docIntel2Env = docIntelInstanceCount >= 2 ? [
  {
    name: 'AZURE_DOC_INTEL_ENDPOINT_2'
    secretRef: 'docintel-endpoint-secret-2'
  }
  {
    name: 'AZURE_DOC_INTEL_KEY_2'
    secretRef: 'docintel-key-secret-2'
  }
] : []

var docIntel3Env = docIntelInstanceCount >= 3 ? [
  {
    name: 'AZURE_DOC_INTEL_ENDPOINT_3'
    secretRef: 'docintel-endpoint-secret-3'
  }
  {
    name: 'AZURE_DOC_INTEL_KEY_3'
    secretRef: 'docintel-key-secret-3'
  }
] : []

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
      secrets: concat(baseSecrets, docIntel2Secrets, docIntel3Secrets)
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
              // Gap 422: 80, NOT 8000. `chromaHost` is an Azure Container Apps
              // *internal ingress* FQDN, and ACA publishes internal ingress on 80
              // (http) and 443 (https). The chromadb app's `targetPort: 8000` is
              // the port its container listens on inside the replica -- it is not
              // what the FQDN serves. Connecting to <fqdn>:8000 reaches nothing
              // and hangs until the client timeout fires.
              //
              // This was 8000 from at least revision --0000116 to --0000122, and
              // every one of those revisions fell back to an empty in-container
              // PersistentClient, so dev vector search returned nothing for the
              // whole period. It looked like a cold-start race because the
              // failure landed at ~3.1s against a 3.0s connect budget; raising
              // that budget to 15s changed nothing except how long it took to
              // fail, which is what finally ruled the race out.
              //
              // If this is ever changed to 443, set CHROMA_USE_SSL true with it.
              name: 'CHROMA_PORT'
              value: '80'
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
              name: 'AZURE_OPENAI_FAST_DEPLOYMENT_NAME'
              value: azureOpenAiFastDeploymentName
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
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            {
              name: 'AZURE_STORAGE_CONNECTION_STRING'
              secretRef: 'storage-conn-secret'
            }
            {
              name: 'GOOGLE_CLIENT_ID'
              value: googleClientId
            }
            {
              name: 'GOOGLE_CLIENT_SECRET'
              secretRef: 'google-client-secret-secret'
            }
            {
              name: 'SALESFORCE_CLIENT_ID'
              value: salesforceClientId
            }
            {
              name: 'SALESFORCE_CLIENT_SECRET'
              secretRef: 'salesforce-client-secret-secret'
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
              name: 'SENDGRID_FROM_EMAIL'
              value: sendgridFromEmail
            }
            {
              name: 'SENDGRID_FROM_NAME'
              value: sendgridFromName
            }
            {
              name: 'EMAIL_APP_DOMAIN'
              value: emailAppDomain
            }
            {
              name: 'EMAIL_APP_ADDRESS'
              value: emailAppAddress
            }
            {
              name: 'SUPPORT_NOTIFY_EMAIL'
              value: supportNotifyEmail
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              // Feature 27 E1/E2 and Feature 26 B11. Process-wide, never
              // per-tenant. Both default false in `config.py` for the same
              // fail-closed reason every flag here does -- a deployment that has
              // not thought about this gets today's behaviour.
              //
              // WHY THESE MUST BE DECLARED EVEN WHEN FALSE: before this, neither
              // name existed as an env var on the container app at all, so there
              // was nothing an operator could flip and no way to see from Azure
              // what the running process believed (BE Gap 402).
              name: 'ENABLE_GENERIC_EXTRACTION'
              value: enableGenericExtraction ? 'true' : 'false'
            }
            {
              name: 'ENABLE_GENERIC_DOC_CHAT'
              value: enableGenericDocChat ? 'true' : 'false'
            }
            {
              // Feature 26 E-5 / H7. The wiring is BUILT and tested -- H7 removed
              // the force-sync clause in `routers/chat.py` -- but this stays false
              // until a Redis instance exists in the environment. `REDIS_URL` is
              // empty on both apps today and there is no Redis container in
              // rg-invoice-llm-dev, so flipping this would enqueue turns nothing
              // ever dequeues. Declared so the switch is visible and versioned
              // rather than discovered later (the BE Gap 402 lesson).
              name: 'ENABLE_ASYNC_CHAT_QUEUE'
              value: enableAsyncChatQueue ? 'true' : 'false'
            }
            {
              name: 'ENABLE_CHAT_STREAMING'
              value: enableChatStreaming ? 'true' : 'false'
            }
          ], docIntel2Env, docIntel3Env)
          // Gap 41/42 scaling (Jul 2026): 2 additional Doc Intelligence
          // resources, round-robined in code (utils/doc_intel_client.py).
          // Each Key Vault secret needs its own env var - Container Apps
          // can't join multiple secretRefs into one comma-separated value.
          // Wired in above via docIntel2Env/docIntel3Env, gated on
          // docIntelInstanceCount so dev (=1) doesn't reference Key Vault
          // secrets that Stage 5 never seeded.
        }
      ]
      scale: {
        minReplicas: minReplicas
        // Reconciled to match the live value (Jul 2026) - this bicep
        // previously said 5 while the deployed resource was actually 10,
        // provisioned out-of-band at some point (see Gap 41 in
        // be_features_tracker.md for the drift this caused).
        maxReplicas: maxReplicas
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
                queueLength: queueScaleLength
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
