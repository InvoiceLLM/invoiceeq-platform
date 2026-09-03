targetScope = 'resourceGroup'

// ============ Feature 26 Part 2 task H9: the chat-attachment TTL sweep job, and nothing else ============
//
// Why this file exists instead of just deploying Stage 8
// -------------------------------------------------------
// Same reason as `infra/emit-online-signals-job-only.bicep`, `infra/benchmark-eval-job-only.bicep`
// and `infra/alert-ai-eval-critical-only.bicep` -- `params.dev.json` names a registry
// that does not exist and a naming prefix this environment was not built with
// (Gap 298, `docs/be_features_tracker.md`), so a full Stage 8 (`08-apps.bicep`)
// deploy against the live dev environment is not safe. This file deploys the one
// new resource this gap needs, over the same shared `modules/compute/scheduled-job.bicep`
// every other scheduled job in this repo uses, with defaults that match what is
// **actually deployed**.
//
//   az deployment group what-if --resource-group rg-invoice-llm-dev \
//     --template-file infra/chat-doc-ttl-job-only.bicep
//   az deployment group create   --resource-group rg-invoice-llm-dev \
//     --template-file infra/chat-doc-ttl-job-only.bicep
//
// What this runs: `scripts/sweep_chat_attachments.py` (Feature 26 decision E-7,
// task H8). Chat attachments are the first thing in this system with a genuine
// finite lifetime -- unlike invoice chunks (deliberately un-swept so a restored
// invoice keeps its chunks), an attachment is a transient artifact of one
// conversation with a vector footprint in `chat_docs_{tenant_id}` that nothing
// else in the repo cleans up. Per expired row the script deletes, IN THIS ORDER,
// chunks then blob then row -- each step best-effort/logged, row last so a crash
// mid-sweep leaves a row that is simply re-swept rather than an orphan with
// nothing pointing at it. `expires_at IS NULL` means KEEP FOREVER (every Part 1
// attachment predates the column) -- the script's own query is
// `expires_at IS NOT NULL AND expires_at <= now`, never the epoch-as-expired
// misreading its docstring warns about.
//
// Cadence: daily, matching the shape of the two other daily row-sweeps already
// in this environment (`caj-overdue-sweep-dev`, `caj-sandbox-sweep-dev`) --
// there is no reason for a TTL cleanup to run more often than once a day.
// Slot chosen: 05:00 UTC. Taken slots as of this deploy, read off the other
// `*-job-only.bicep` files and `08-apps.bicep` directly rather than assumed:
//   00:00/06:00/12:00/18:00 + :15  -- caj-online-signals-dev
//   02:00                          -- caj-overdue-sweep-dev (overdueSweepCron)
//   03:00                          -- caj-benchmark-eval-dev (benchmarkEvalCron)
//   04:00                          -- caj-sandbox-sweep-dev (sandboxSweepCron)
//   06:00                          -- caj-billing-lifecycle-dev
// 05:00 collides with none of them -- it sits in the one clear hour between
// caj-sandbox-sweep-dev (04:00) and caj-billing-lifecycle-dev (06:00).
//
// replicaTimeout: 1800s (the module default, same value `caj-overdue-sweep-dev`
// and `caj-sandbox-sweep-dev` use unchanged). This job is the same *shape* of
// work as those two -- a bounded Postgres SELECT followed by a per-row loop of
// best-effort network deletes (Chroma chunk delete, blob delete) and a commit --
// not the LLM-heavy work `caj-benchmark-eval-dev` was sized to 5400s for. No
// LLM call anywhere in this script, so 30 minutes is generous headroom for a
// dev-sized backlog rather than a measured worst case.
//
// --limit on this first deploy: the script's own `--limit` help text says a
// long-lived environment's first run may have a large backlog and a bounded
// first pass is easier to inspect than an unbounded one. This dev environment
// has been running since before the `expires_at` column existed (H4), so the
// true backlog size is unknown going in -- passing `--limit 500` here follows
// that guidance directly for the first (and every subsequent, until this file
// is redeployed with a different value) scheduled run, rather than betting an
// unbounded first pass is fine on the strength of it probably being fine.
//
// No LLM, no RAG call anywhere in this script -- `azureOpenAiEndpoint`/
// `azureOpenAiDeploymentName` are left at the module's empty-string defaults.
// `chromaHost` is still wired (same `existing` lookup every other job in this
// file uses) only because `config.py` reads `CHROMA_HOST`/`CHROMA_PORT` at
// import time with no default -- the module's own comment on that param --
// even though this script's own Chroma work goes through
// `services/chat_document_search.py::delete_attachment_chunks()`, not a direct
// client call here.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm` — the prefix this environment was ACTUALLY built with — not params.dev.json\'s `invoice-llm`.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image. Defaults to the one registry that exists (`acrinvoicellmdev2`).')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. Any build containing scripts/sweep_chat_attachments.py -- committed under Feature 26 task H8/H9.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Cron (UTC). Daily at 05:00 -- the one clear hour between caj-sandbox-sweep-dev\'s 04:00 and caj-billing-lifecycle-dev\'s 06:00; see the header comment for the full list of taken slots this avoids.')
param chatDocTtlCron string = '0 5 * * *'

@description('Seconds before the execution is killed. Same shape of work (bounded SELECT + per-row best-effort network deletes, no LLM call) as caj-overdue-sweep-dev/caj-sandbox-sweep-dev, so left at the module\'s own 1800s default rather than benchmark-eval\'s LLM-sized 5400s.')
param chatDocTtlReplicaTimeout int = 1800

@description('Cap on rows this run touches, passed as --limit. See header comment: the first run against a long-lived, backlog-unknown environment is easier to inspect bounded than unbounded.')
param chatDocTtlLimit int = 500

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

module chatDocTtlJob './modules/compute/scheduled-job.bicep' = {
  name: 'chat-doc-ttl-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-chat-doc-ttl-${environment}'
    containerName: 'chat-doc-ttl'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
    command: [
      'python'
      'scripts/sweep_chat_attachments.py'
    ]
    args: [
      '--limit'
      string(chatDocTtlLimit)
    ]
    cronExpression: chatDocTtlCron
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    appInsightsConnectionString: appInsights.properties.ConnectionString
    cpu: '0.5'
    memory: '1.0Gi'
    replicaTimeout: chatDocTtlReplicaTimeout
  }
}

output jobName string = chatDocTtlJob.outputs.jobName
output jobId string = chatDocTtlJob.outputs.jobId
