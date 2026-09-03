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

// Gap 8: required for Clerk JWT verification. Without CLERK_JWKS_URL,
// dependencies.py -> get_jwk() raises HTTP 500 on every real token. Without
// CLERK_JWT_ISSUER, issuer validation is silently skipped and a correctly signed
// token from ANY Clerk tenant would be accepted.
//
// Not secrets: the JWKS endpoint is public and unauthenticated by design, and the
// issuer is a public URL present in every token's `iss` claim.
@description('Clerk JWT issuer URL (public, no trailing slash)')
param clerkJwtIssuer string = ''

@description('Clerk JWKS endpoint URL (public)')
param clerkJwksUrl string = ''

// config.py's ALLOWED_ORIGINS default is localhost-only (dev fallback) --
// nothing previously set a real value here, so CORS would silently reject
// every real deployed frontend origin. Not currently exploitable (ingress
// below is external:false, so a browser can never reach this app directly),
// but wrong-by-default is worth fixing before anyone flips that to true.
@description('Comma-separated allowed CORS origins (real FE/website FQDNs, computed by the orchestrator)')
param allowedOrigins string = ''

// Connectors (Feature 9): one shared platform-level OAuth app per provider
// (our company's), not per-tenant -- see routers/connectors.py. Client IDs
// and redirect URIs are public (visible in the browser's OAuth redirect),
// so they're plain params here; only the client secrets come from Key Vault.
@description('Our company Google Cloud OAuth Client ID (connectors: Drive)')
param googleClientId string = ''

@description('OAuth redirect URI registered with Google for this environment')
param googleRedirectUri string = ''

@description('Our company Salesforce Connected App Consumer Key (connectors)')
param salesforceClientId string = ''

@description('OAuth redirect URI registered with Salesforce for this environment')
param salesforceRedirectUri string = ''

// SendGrid (Gap 124/125): one platform-wide domain, not per-tenant -- see
// feature_9_connectors.md. The sending domain name itself isn't sensitive
// (same treatment as the OAuth redirect URIs above); the API key and inbound
// webhook shared secret are, so those come from Key Vault below instead.
@description('SendGrid-authenticated domain used as the technical From for outbound mail (Gap 125) -- e.g. admsofttech.com')
param sendgridSendingDomain string = ''

@description('Full From address for outbound emails -- e.g. invoices@outbound.invoicellm.admsofttech.com')
param sendgridFromEmail string = ''

@description('Display name for outbound emails -- e.g. InvoiceLLM Platform')
param sendgridFromName string = 'InvoiceLLM Platform'

@description('Inbound mail domain (MX target for SendGrid Inbound Parse) -- e.g. inbound.invoicellm.admsofttech.com')
param emailAppDomain string = ''

@description('Platform-wide mailbox address tenants send invoices to -- e.g. invoices@outbound.invoicellm.admsofttech.com')
param emailAppAddress string = ''

@description('Support / ops alert destination inbox -- never set to empty, that would silently swallow every ticket')
param supportNotifyEmail string = ''

@description('Public browser origin for full-page redirects after connector OAuth (settings/connectors). Must be the invoice-website FQDN under Multi-Zone — FE is internal-only and returns Azure\'s "stopped or does not exist" page if the browser is sent there.')
param frontendUrl string = ''

// Feature 11 PayU: key/salt come from Key Vault (Stage 5). Mode and the two
// public website origins are plain params -- not secrets.
@description('PayU environment: test -> test.payu.in, live -> secure.payu.in')
param payuMode string = 'test'

@description('Public origin PayU POSTs surl/furl to -- invoice-website FQDN (be ingress is internal-only; website relays /api/v1/billing/payu/*)')
param backendPublicUrl string = ''

@description('Public origin for /billing/success and /billing/failed redirects after PayU -- invoice-website FQDN')
param publicAppUrl string = ''

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Application Insights Connection String for OpenTelemetry APM tracing')
param appInsightsConnectionString string = ''

// Feature 23 / Gap 304 half (2), enabled live on dev 2026-08-26: gates
// services/online_quality_judge.py::submit_turn_judgement(), called from
// routers/chat.py after every real chat response. Off is a complete no-op
// (config.py's own comment: the submit helper checks this flag before
// handing anything to the background thread pool, so nothing runs at all
// with it false). On, it adds two billable LLM calls per real chat turn
// (combined soft judge + persona judge) and occupies one of the chat
// background pool's 8 workers for the duration -- a real per-tenant cost
// and, under heavy load, a background-work-delay tradeoff, which is why
// this defaults false here and is opted in per environment via
// params.dev.json / params.prod.json rather than arriving on by default.
@description('Score every real production chat turn with the online quality judge (Gap 304), writing an agent_eval_run row tagged run_source=production. Default false -- opt in per environment.')
param enableProductionQualityJudge bool = false

@description('Feature 27 — generic (non-invoice) extraction. Gates the classifier node in the extraction graph; with it off `doc_type` is always None and no `documents` row is ever created. Opt in per environment, exactly like enableProductionQualityJudge above.')
param enableGenericExtraction bool = false

@description('Feature 26 Part 2 — the attached-document intent split and content branch. With it off an attachment turn is Part 1\'s deterministic comparison path, byte-identical to Gap 366. NOT a gate on attachments as such (B11 item 1: `attachment_id` presence is the routing switch and is not a flag).')
param enableGenericDocChat bool = false

@description('Feature 26 E-5 / task H7 — route an attachment chat turn through the Redis-backed async queue instead of answering it synchronously. REQUIRES a reachable REDIS_URL: `services/chat_queue.py::get_redis_client()` returns None when it is empty, so enabling this without Redis enqueues into nothing. Declared here for documentation and later rollout; dev has no Redis deployed as of 2026-09-03, so it stays false.')
param enableAsyncChatQueue bool = false

@description('Subscription ID services/azure_cost.py and ops_recommendation.py read Cost Management / Resource Graph from. Declared in config.py but never wired here until now -- without it, the cost sweep and the nightly recommendation pass cost/container_health categories both fail with "not configured".')
param azureSubscriptionId string = subscription().subscriptionId

@description('Resource group the cost/container-health reads are scoped to.')
param azureCostResourceGroup string = resourceGroup().name

@description('vCPU allocation, e.g. \'1.0\'. Passed to json() below since Container Apps requires cpu as a decimal, not a string.')
param cpu string = '1.0'

@description('Memory allocation, e.g. \'2.0Gi\'.')
param memory string = '2.0Gi'

@description('Minimum replica count.')
param minReplicas int = 1

@description('Maximum replica count.')
param maxReplicas int = 5

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
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
      ingress: {
        external: false // Accessible only internally (VNet/Frontend)
        targetPort: 8000
        transport: 'http'
        // Feature 19 (Timeout Fix): Explicit 2-minute ceiling so the ACA
        // ingress layer gives the backend enough time for a full chat
        // pipeline (classify → SQL/RAG LLM call → DB → answer synthesis).
        // Without this the effective ceiling is an undocumented Azure default
        // that varies by region/ACA version and can cut connections before
        // OpenAI has had a chance to respond.
        timeoutInSeconds: 120
      }
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
        // Secret name kept as 'sendgrid-key-secret' (not 'sendgrid-api-key-secret') to
        // match the name already wired live on 2026-08-26 via `az containerapp secret set`.
        // Renaming would require a live delete+recreate of the secret reference.
        {
          name: 'sendgrid-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/SENDGRID-API-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'sendgrid-inbound-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/SENDGRID-INBOUND-SECRET'
          identity: userAssignedIdentityId
        }
        {
          name: 'payu-merchant-key-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/PAYU-MERCHANT-KEY'
          identity: userAssignedIdentityId
        }
        {
          name: 'payu-merchant-salt-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/PAYU-MERCHANT-SALT'
          identity: userAssignedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'invoice-be'
          image: image
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
              name: 'CLERK_JWT_ISSUER'
              value: clerkJwtIssuer
            }
            {
              name: 'CLERK_JWKS_URL'
              value: clerkJwksUrl
            }
            {
              name: 'ALLOWED_ORIGINS'
              value: allowedOrigins
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
              name: 'GOOGLE_REDIRECT_URI'
              value: googleRedirectUri
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
              name: 'SALESFORCE_REDIRECT_URI'
              value: salesforceRedirectUri
            }
            {
              name: 'SENDGRID_API_KEY'
              secretRef: 'sendgrid-key-secret'
            }
            {
              name: 'INBOUND_PARSE_SHARED_SECRET'
              secretRef: 'sendgrid-inbound-secret'
            }
            {
              name: 'AZURE_SUBSCRIPTION_ID'
              value: azureSubscriptionId
            }
            {
              name: 'AZURE_COST_RESOURCE_GROUP'
              value: azureCostResourceGroup
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
              name: 'PAYU_MERCHANT_KEY'
              secretRef: 'payu-merchant-key-secret'
            }
            {
              name: 'PAYU_MERCHANT_SALT'
              secretRef: 'payu-merchant-salt-secret'
            }
            {
              name: 'PAYU_MODE'
              value: payuMode
            }
            {
              name: 'BACKEND_PUBLIC_URL'
              value: backendPublicUrl
            }
            {
              name: 'PUBLIC_APP_URL'
              value: publicAppUrl
            }
            {
              name: 'FRONTEND_URL'
              value: frontendUrl
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              // Gap 304 half 2: two extra LLM calls per chat turn when on --
              // opt in per environment, never on by default.
              name: 'ENABLE_PRODUCTION_QUALITY_JUDGE'
              value: enableProductionQualityJudge ? 'true' : 'false'
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
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 15
              periodSeconds: 15
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/readiness'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              failureThreshold: 12
              timeoutSeconds: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas  // 1 — always one warm replica for instant response
        maxReplicas: maxReplicas  // 5 — burst headroom for high-traffic periods
        rules: [
          {
            // HTTP concurrent-request trigger: fires when more than 20 requests
            // are in-flight simultaneously (e.g. 50 users all chatting at once).
            // Each chat request holds a connection open for 5-15s waiting on
            // OpenAI, so concurrent count is a better load signal than RPS here.
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
          {
            // CPU trigger: fires before the 80% memory alert threshold.
            // Catches heavy-workload scenarios with few concurrent requests —
            // e.g. 3 users uploading large PDFs simultaneously. Doc Intelligence
            // + OpenAI extraction drives CPU up even though only 3 HTTP
            // connections are open, so the HTTP rule alone would miss this.
            // Gap 290 (2026-08-23): threshold raised 70 -> 85 per founder
            // decision — this rule and the memory one below existed only in
            // source until now; the live resource had no scale rules at all
            // (`az containerapp show` returned `rules: null`), so Azure was
            // silently falling back to its platform default (~10 concurrent
            // req/replica) despite this reasoning being written down.
            name: 'cpu-scaling'
            custom: {
              type: 'cpu'
              metadata: {
                type: 'Utilization'
                value: '85'
              }
            }
          }
          {
            // Memory trigger, added Gap 290 (2026-08-23): the CPU rule alone
            // misses a memory-bound-but-CPU-light scenario (e.g. holding many
            // large tool-result payloads in memory across concurrent chat
            // turns without a proportional CPU cost).
            name: 'memory-scaling'
            custom: {
              type: 'memory'
              metadata: {
                type: 'Utilization'
                value: '85'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = backendApp.properties.configuration.ingress.fqdn
