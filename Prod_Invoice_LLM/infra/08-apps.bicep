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

// Gap 124/125's remaining 5 SendGrid/email params were never threaded through
// this orchestration file -- invoice-be.bicep declares them, but nothing here
// passed real values into that module call, so the live-correct values on
// ca-invoice-be-dev exist only because someone set them directly via
// `az containerapp update --set-env-vars`, bypassing bicep entirely. The next
// full bicep deploy would have silently reset them to blank defaults. Also
// newly threaded into queue-worker.bicep (queueWorker module below), which
// never received any of these 6 at all -- the real bug this closes: the
// worker is what actually runs notify_processing_complete()/
// notify_auditor_action(), and with no SENDGRID_API_KEY it silently
// no-ops on every invoice, worker-wide, regardless of status.
@description('Full From address for outbound emails -- public value, see invoice-be.bicep')
param sendgridFromEmail string = ''

@description('Display name for outbound emails -- public value, see invoice-be.bicep')
param sendgridFromName string = 'InvoiceLLM'

@description('Inbound mail domain (MX target for SendGrid Inbound Parse) -- public value, see invoice-be.bicep')
param emailAppDomain string = ''

@description('Platform-wide mailbox address tenants send invoices to -- public value, see invoice-be.bicep')
param emailAppAddress string = ''

@description('Support / ops alert destination inbox -- public value, see invoice-be.bicep')
param supportNotifyEmail string = ''

@description('PayU mode for invoice-be (Feature 11). test|live. Merchant key/salt are seeded in Stage 5 Key Vault, not here.')
param payuMode string = 'test'

@description('Score every real production chat turn with the online quality judge (Gap 304). Default false -- see invoice-be.bicep for the cost/latency tradeoff this opts into. Set true only where wanted, per environment (params.dev.json/params.prod.json).')
param enableProductionQualityJudge bool = false

@description('Feature 27 — generic (non-invoice) extraction. Gates the classifier node in the extraction graph; with it off `doc_type` is always None and no `documents` row is ever created. Opt in per environment, exactly like enableProductionQualityJudge above.')
param enableGenericExtraction bool = false

@description('Feature 26 Part 2 — the attached-document intent split and content branch. With it off an attachment turn is Part 1\'s deterministic comparison path, byte-identical to Gap 366. NOT a gate on attachments as such (B11 item 1: `attachment_id` presence is the routing switch and is not a flag).')
param enableGenericDocChat bool = false

@description('Feature 26 E-5 / task H7 — route an attachment chat turn through the Redis-backed async queue instead of answering it synchronously. REQUIRES a reachable REDIS_URL: `services/chat_queue.py::get_redis_client()` returns None when it is empty, so enabling this without Redis enqueues into nothing. Declared here for documentation and later rollout; dev has no Redis deployed as of 2026-09-03, so it stays false.')
param enableAsyncChatQueue bool = false

@description('Subscription ID for services/azure_cost.py and ops_recommendation.py -- see invoice-be.bicep for why this was missing.')
param azureSubscriptionId string = subscription().subscriptionId

@description('Resource group the cost/container-health reads are scoped to.')
param azureCostResourceGroup string = resourceGroup().name

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

// Gap 345: nothing scheduled scripts/sweep_sandbox_tenants.py (Gap 340), so
// unclaimed/expired sandbox tenants accumulated forever and
// services/sandbox.py::unclaimed_sandbox_count()'s hard global cap (500,
// counted regardless of expiry, by design) would eventually make sandbox-key
// issuance fail closed for everyone under ordinary usage, with no automated
// recovery. Daily, same cadence as the other sweep jobs -- there is no reason
// sandbox cleanup needs to run more often, since the auth check
// (`resolve_api_key_context()`) already closes access at expiry independent
// of this job; this job only reclaims the row and the count. 04:00 UTC: clear
// of caj-overdue-sweep's 02:00, caj-benchmark-eval's 03:00 and
// caj-billing-lifecycle's 06:00.
@description('Cron schedule (UTC) for the sandbox-tenant reap sweep. Daily at 04:00 UTC by default.')
param sandboxSweepCron string = '0 4 * * *'

@description('vCPU allocation for scheduled jobs.')
param scheduledJobCpu string = '0.5'

@description('Memory allocation for scheduled jobs.')
param scheduledJobMemory string = '1.0Gi'

// Feature 23 (AI Control Tower), rescoped 2026-08-23. Runs both benchmark
// tracks -- scripts/run_extraction_benchmark.py (Track 1) and
// scripts/run_agent_eval.py (Track 2) -- nightly. 03:00 UTC: after
// caj-overdue-sweep-dev's 02:00, matching the old (deleted) caj-agent-eval-dev
// job's schedule, which was never in conflict with anything. (It was also
// chosen to stay clear of Feature 24's caj-ops-digest-dev 01/07/13/19:00
// slots; that feature was superseded and deleted 2026-08-25, so 03:00 is now
// only constrained by the overdue sweep.)
@description('Cron schedule (UTC) for the nightly Feature 23 benchmark/eval job.')
param benchmarkEvalCron string = '0 3 * * *'

// Sized off a real measured run on 2026-08-23 against the live
// openai-invoicellm-dev gpt-5-mini deployment (see
// feature_23_ai_control_tower.md's "Nightly scheduler as built" section), not
// a guess: `--mode live` (9 real extractions) took ~5 minutes; the 20-case
// default-path chat suite (separate judge, the runner's own default) was
// timed at roughly 2 minutes/turn over a real partial run and extrapolates to
// ~40 minutes for all 20. ~45 minutes measured/extrapolated total, so 90
// minutes is roughly 2x headroom -- generous but not open-ended, so a genuine
// hang still gets killed before the next scheduled execution.
@description('Seconds before the nightly benchmark/eval job execution is killed.')
param benchmarkEvalReplicaTimeout int = 5400

// This job imports the same agent/graph/SQL stack as ca-invoice-be itself
// (agents.query_agent, agents.extraction_agent, langgraph, sqlalchemy,
// azure-ai-documentintelligence) -- not the "a few queries plus outbound
// HTTP" shape scheduledJobCpu/scheduledJobMemory's defaults were sized for
// (see their own description above) -- so it gets its own, larger allocation
// rather than sharing that pair.
@description('vCPU allocation for the nightly benchmark/eval job.')
param benchmarkEvalCpu string = '1.0'

@description('Memory allocation for the nightly benchmark/eval job.')
param benchmarkEvalMemory string = '2.0Gi'

@description('Website Container App vCPU allocation.')
param websiteCpu string = '0.5'
@description('Website Container App memory allocation.')
param websiteMemory string = '1.0Gi'
@description('Website Container App minimum replica count. Dev default 0 (scale-to-zero); prod should set >=1 to avoid cold-starts on the public entry point.')
param websiteMinReplicas int = 1
@description('Website Container App maximum replica count.')
param websiteMaxReplicas int = 3

@description('Custom domain for the public website (e.g. "invoiceeq.app"), once purchased. Empty by default -- leaving this unset deploys nothing new (no Front Door, no CORS/redirect-URI changes) and every existing CAE-domain URL keeps working exactly as before. See feature_6_custom_domain_integration.md for the full cutover sequence once a domain is bought.')
param customDomainName string = ''

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
// Hyphens stripped from namingPrefix, matching the real live resource
// (`appi-invoicellm-dev`, not `appi-invoice-llm-dev`) -- App Insights names
// can contain hyphens so this isn't an Azure naming requirement like
// storageAccountName's strip below, just matching what already exists.
var appInsightsName = 'appi-${replace(namingPrefix, '-', '')}-${environment}'

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

// Once a real domain is purchased and Front Door is live in front of the
// website (see the frontDoor module below), that domain becomes the
// canonical public origin -- OAuth callbacks, BACKEND_PUBLIC_URL,
// PUBLIC_APP_URL and FRONTEND_URL all switch wholesale to it. Falls back to
// the CAE FQDN otherwise, so leaving customDomainName unset changes nothing.
var publicOrigin = empty(customDomainName) ? websiteFqdn : customDomainName

// OAuth redirect URIs must be the public origin (website), not the backend or internal frontend --
// backendApp and frontendApp are both internal-only (external:false), so Google/Salesforce
// redirect the browser back to the website, which proxies it to the frontend container.
var googleRedirectUri = 'https://${publicOrigin}/api/connectors/callback/google_drive'
var salesforceRedirectUri = 'https://${publicOrigin}/api/connectors/callback/salesforce'

// CORS stays additive, not a switch -- the CAE FQDN keeps working (useful
// during DNS/cert cutover, and as a fallback if Front Door is ever bypassed)
// while the custom domain is added alongside it once set.
var corsAllowedOrigins = empty(customDomainName)
  ? 'https://${frontendFqdn},https://${websiteFqdn}'
  : 'https://${frontendFqdn},https://${websiteFqdn},https://${customDomainName}'

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
    allowedOrigins: corsAllowedOrigins
    googleClientId: googleClientId
    googleRedirectUri: googleRedirectUri
    salesforceClientId: salesforceClientId
    salesforceRedirectUri: salesforceRedirectUri
    sendgridSendingDomain: sendgridSendingDomain
    sendgridFromEmail: sendgridFromEmail
    sendgridFromName: sendgridFromName
    emailAppDomain: emailAppDomain
    emailAppAddress: emailAppAddress
    supportNotifyEmail: supportNotifyEmail
    payuMode: payuMode
    backendPublicUrl: 'https://${publicOrigin}'
    publicAppUrl: 'https://${publicOrigin}'
    appInsightsConnectionString: appInsights.properties.ConnectionString
    // Post-Multi-Zone: browser never reaches FE (ingress external:false). Any
    // full-page RedirectResponse (e.g. connectors oauth_callback) must land on
    // the public website origin, which proxies /settings/* to FE.
    frontendUrl: 'https://${publicOrigin}'
    cpu: backendCpu
    memory: backendMemory
    minReplicas: backendMinReplicas
    maxReplicas: backendMaxReplicas
    enableProductionQualityJudge: enableProductionQualityJudge
    enableGenericExtraction: enableGenericExtraction
    enableGenericDocChat: enableGenericDocChat
    enableAsyncChatQueue: enableAsyncChatQueue
    azureSubscriptionId: azureSubscriptionId
    azureCostResourceGroup: azureCostResourceGroup
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
    enableGenericExtraction: enableGenericExtraction
    enableGenericDocChat: enableGenericDocChat
    enableAsyncChatQueue: enableAsyncChatQueue
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
    appInsightsConnectionString: appInsights.properties.ConnectionString
    // Gap 180: same company OAuth apps as invoice-be — worker needs them to
    // download Drive/Salesforce files and refresh tokens during import.
    googleClientId: googleClientId
    salesforceClientId: salesforceClientId
    // Newly wired: the worker runs notify_processing_complete()/
    // notify_auditor_action() (services/staff_notify.py, called from
    // queue_worker/handlers.py) but never had SendGrid config at all -- every
    // completion/audit notification silently no-op'd, worker-wide, with no
    // error (sendgrid_configured() soft-skip). See queue-worker.bicep.
    sendgridSendingDomain: sendgridSendingDomain
    sendgridFromEmail: sendgridFromEmail
    sendgridFromName: sendgridFromName
    emailAppDomain: emailAppDomain
    emailAppAddress: emailAppAddress
    supportNotifyEmail: supportNotifyEmail
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
    appInsightsConnectionString: appInsights.properties.ConnectionString
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
    appInsightsConnectionString: appInsights.properties.ConnectionString
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

// Gap 345 (BE Gap 340's own tracker entry recorded this as not done: "No ACA
// Job schedules the reaper"): the sandbox-tenant reap sweep
// (scripts/sweep_sandbox_tenants.py). Same shape as overdueSweepJob directly
// above -- reuses `backendImage`, the generic scheduled-job.bicep module (not
// billing-lifecycle-job.bicep's dedicated, minimal-secrets module: that
// module wires only DATABASE_URL, but this script's import chain
// (database.py -> config.py, services/sandbox.py -> config.get_settings())
// pulls in the same required-with-no-default Settings fields
// (REDIS_URL/CHROMA_HOST/CHROMA_PORT/CLERK_SECRET_KEY/TOKEN_ENCRYPTION_KEY)
// scheduled-job.bicep's header comment documents and provisions -- so this
// follows the proven-complete env/secret wiring, not the narrower one).
module sandboxSweepJob './modules/compute/scheduled-job.bicep' = {
  name: 'sandbox-sweep-job-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-sandbox-sweep-${environment}'
    containerName: 'sandbox-sweep'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: sharedAcrName
    image: backendImage
    command: [
      'python'
      'scripts/sweep_sandbox_tenants.py'
    ]
    cronExpression: sandboxSweepCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    cpu: scheduledJobCpu
    memory: scheduledJobMemory
  }
}

// Feature 24 (the Ops Digest Agent) declared a `caj-ops-digest-<env>` job here,
// on `0 1,7,13,19 * * *` over the same scheduled-job.bicep module. It was never
// deployed, and the feature was superseded as over-scoped on 2026-08-25; the
// module block, its `opsDigestCron`/`opsDigestDelivery` params and the whole
// backend implementation were deleted with it (Gap 311). The generic
// `extraEnv`/`extraSecrets` parameters on scheduled-job.bicep were added for
// that job and are kept -- they are job-agnostic and benchmarkEvalJob uses the
// same module. Full history: `git log -- Prod_Invoice_LLM/infra/08-apps.bicep`,
// commit `bce9e38`.

// Feature 23's original nightly golden-bank eval job (caj-agent-eval-dev) was
// deployed, then deleted 2026-08-23 along with the rest of that build
// (9-workbook split, golden_bank.json) when the founder and architect
// rethought Feature 23's actual scope from scratch -- see
// feature_23_ai_control_tower.md's dated section. This is that section's
// replacement: both of the rebuilt tracks (Track 1 extraction/alert
// benchmark, Track 2 chat eval), run nightly in one job execution.
//
// One container, two scripts: scheduled-job.bicep's template is a single
// command, so the two are chained with a shell `&&` rather than declaring two
// jobs (which would need two separate cron-collision checks and double the
// cold-start/import cost for no benefit -- both scripts already import most
// of the same module tree).
//
// `--no-gate` on Track 1: the corpus's one known, deliberately-not-fixed
// false positive (Gap 293, outbound_trade_discount__clean -- see
// feature_23_ai_control_tower.md, "The defect the first run found") would
// otherwise make this job report Failed every single night on a
// non-regression, which defeats using the job's own execution status as a
// signal. The pre-deploy gate (.github/workflows/deploy-dev.yml) is where
// Track 1 actually gates something, using --tolerate-fp for the same case
// instead of --no-gate, because a CI job's pass/fail IS the signal there.
//
// As of 2026-08-24, that pre-deploy gate is not a second job/bicep resource
// -- it is `az containerapp job start --command/--args ...` against this
// SAME caj-benchmark-eval-${environment} job, overriding the container
// command for that one on-demand execution only (the override is
// per-execution; it never touches this module's persisted `args` below, so
// the 03:00 UTC Schedule trigger keeps running the full/live/--no-gate
// command unmodified regardless of how many times the gate has fired that
// day). See `benchmark-eval-job-only.bicep`'s header and the
// `benchmark-gate` job's own header comment in deploy-dev.yml for the full
// rationale -- keep this note and both of those in sync if the mechanism
// changes.
//
// `--no-write` on Track 1: a Container Apps Job replica's filesystem is
// ephemeral (no volume is mounted here), so writing
// docs/extraction_benchmark/runs/ artifacts inside the container would just
// be discarded when the replica exits -- --json keeps the scored summary in
// the execution's own stdout instead, which Container Apps Job execution
// history / Log Analytics does retain. This flag only controls the local
// review-corpus files, not telemetry.
//
// `--run-label nightly` on BOTH tracks (2026-08-24): each script now mirrors
// its own scored run out of the process -- one aggregate custom event
// (extraction_benchmark_run / agent_eval_summary) plus the full raw JSON to
// the benchmark-artifacts blob container -- because stdout is not a queryable
// data source for an Azure Monitor workbook. The label is what keeps this
// nightly series apart from the pre-deploy gate's 5-case smoke runs, which
// execute the same two scripts against the same App Insights resource; see
// services/benchmark_artifacts.py. Both halves are non-fatal by contract, so
// neither can fail this job.
//
// Track 2 runs `--paths default` only (not `--paths default,sage`): SAGE
// orchestrator is gated behind ENABLE_AGENTIC_SAGE and off by default today
// (see the feature doc's registry table) -- measuring a path nothing in
// production is taking would add ~40 more minutes and real token cost for a
// path with zero traffic. Uses the runner's own default judge mode
// (`separate`, not `--judge combined`): the feature doc's Track 2 section
// explicitly leaves flipping that default as a "decision required" pending a
// paired judge comparison, not something to make silently from infra.
// run_agent_eval.py also persists its own agent_eval_run rows
// (DATABASE_URL/APPLICATIONINSIGHTS_CONNECTION_STRING, both already wired
// below) -- that per-turn record is the durable Postgres one; the
// agent_eval_summary event `--run-label` produces is the aggregate a workbook
// can actually query, which Postgres is not reachable for.
module benchmarkEvalJob './modules/compute/scheduled-job.bicep' = {
  name: 'benchmark-eval-job-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-benchmark-eval-${environment}'
    containerName: 'benchmark-eval'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: sharedAcrName
    image: backendImage
    command: [
      '/bin/sh'
      '-c'
    ]
    args: [
      'python scripts/run_extraction_benchmark.py --mode live --no-write --no-gate --json --run-label nightly --tolerate-fp outbound_trade_discount__clean && python scripts/run_agent_eval.py --paths default --run-label nightly'
    ]
    cronExpression: benchmarkEvalCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    // Both scripts emit telemetry (extraction's tracked_llm_call() sites,
    // Track 2's track_eval_result()/track_agent_call()) -- without this it
    // would silently no-op to stdout instead of reaching appi-invoicellm-dev.
    appInsightsConnectionString: appInsights.properties.ConnectionString
    cpu: benchmarkEvalCpu
    memory: benchmarkEvalMemory
    replicaTimeout: benchmarkEvalReplicaTimeout
  }
}

// Front Door + WAF (Cloud_Architecture_Document.md section 12, Layer 1 --
// documented at the original design stage but never built until now). Only
// deploys when a real domain has been purchased and set via
// customDomainName; a no-op otherwise. See feature_6_custom_domain_integration.md.
module frontDoor './modules/network/front-door.bicep' = if (!empty(customDomainName)) {
  name: 'front-door-deploy'
  params: {
    namingPrefix: namingPrefix
    environment: environment
    customDomainName: customDomainName
    originHostName: websiteApp.outputs.fqdn
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
output websiteUrl string = websiteApp.outputs.fqdn
output publicUrl string = 'https://${publicOrigin}'
output frontDoorDomainValidationToken string = frontDoor.?outputs.?domainValidationToken ?? ''
output frontDoorEndpointHostName string = frontDoor.?outputs.?frontDoorEndpointHostName ?? ''
