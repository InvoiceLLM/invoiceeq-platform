targetScope = 'resourceGroup'

// ============ Gap 305: the online-eval-signals emitter job, and nothing else ============
//
// Why this file exists instead of just deploying Stage 8
// -------------------------------------------------------
// Same reason as `infra/benchmark-eval-job-only.bicep` and `infra/alert-ai-eval-critical-only.bicep`
// -- `params.dev.json` names a registry that does not exist and a naming prefix
// this environment was not built with (Gap 298, `docs/be_features_tracker.md`),
// so a full Stage 8 (`08-apps.bicep`) deploy against the live dev environment
// is not safe. This file deploys the one new resource this gap needs, over the
// same shared `modules/compute/scheduled-job.bicep` every other scheduled job
// in this repo uses, with defaults that match what is **actually deployed**.
//
//   az deployment group what-if --resource-group rg-invoice-llm-dev \
//     --template-file infra/emit-online-signals-job-only.bicep
//   az deployment group create   --resource-group rg-invoice-llm-dev \
//     --template-file infra/emit-online-signals-job-only.bicep
//
// What this runs: `scripts/emit_online_signals_job.py` (Gap 305) -- reads real
// chat traffic out of Postgres over the trailing window, computes the four live
// online-eval signals (`services/online_eval_signals.py::compute_online_signals()`
// -- `budget_exhaustion_rate` retired from the default set the same day, see
// that module's docstring), and mirrors them onto Application Insights as
// `online_eval_signal` events, which the AI Control Tower workbook's Section F
// (`f1-breached-signals`/`f2-signal-detail`) already queries and has since the
// tiles were built -- they have rendered empty since day one for lack of a
// caller, not for lack of a query.
//
// Cadence and honesty about what it will show at current volume: every 6 hours,
// matching the script's own `--window-hours` default so the workbook's window
// and the job's window agree. Real traffic as of this deploy is roughly 5-6
// chat turns/day -- `MIN_SAMPLE_FOR_ALERT = 20` in `online_eval_signals.py`
// means most 6-hour windows will report "insufficient sample" rather than a
// real rate for some time yet. That is the correct, honest behaviour of the
// signal, not a reason to withhold deploying it -- the alternative is turning
// it on later and starting the trend from zero at the moment it would actually
// start being useful.
//
// No LLM, no RAG, no ChromaDB call anywhere in this script -- `azureOpenAiEndpoint`/
// `azureOpenAiDeploymentName` are left at the module's empty-string defaults.
// `chromaHost` is still wired (via the same `existing` lookup every other job
// in this file uses) only because `config.py` reads `CHROMA_HOST`/`CHROMA_PORT`
// at import time with no default -- the module's own comment on that param.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm` — the prefix this environment was ACTUALLY built with — not params.dev.json\'s `invoice-llm`.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image. Defaults to the one registry that exists (`acrinvoicellmdev2`).')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. Any build containing scripts/emit_online_signals_job.py and services/online_eval_signals.py -- both have existed since Gap 305 was opened, well before this deploy.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Cron (UTC). Every 6 hours, matching emit_online_signals_job.py\'s own --window-hours default, offset from the top of the hour to avoid the 00:00/02:00/03:00 slots caj-overdue-sweep-dev/caj-benchmark-eval-dev already use.')
param onlineSignalsCron string = '15 0,6,12,18 * * *'

@description('Seconds before the execution is killed. This is a handful of read-only Postgres queries plus one telemetry mirror -- far below a benchmark run.')
param onlineSignalsReplicaTimeout int = 600

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
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

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

module onlineSignalsJob './modules/compute/scheduled-job.bicep' = {
  name: 'emit-online-signals-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-online-signals-${environment}'
    containerName: 'online-signals'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/emit_online_signals_job.py'
    ]
    args: [
      '--window-hours'
      '6'
    ]
    cronExpression: onlineSignalsCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    appInsightsConnectionString: appInsights.properties.ConnectionString
    cpu: '0.5'
    memory: '1.0Gi'
    replicaTimeout: onlineSignalsReplicaTimeout
  }
}

output jobName string = onlineSignalsJob.outputs.jobName
output jobId string = onlineSignalsJob.outputs.jobId
