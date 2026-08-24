targetScope = 'resourceGroup'

// ============ Feature 23: the nightly benchmark/eval job, and nothing else ============
//
// Why this file exists instead of just deploying Stage 8
// -------------------------------------------------------
// `08-apps.bicep` already declares this job (module `benchmarkEvalJob`) and that
// is the canonical declaration -- it is what a clean environment build produces.
// But a Stage 8 deploy against the *current* dev environment is not a safe way
// to create it (Gap 298, `docs/be_features_tracker.md`, 2026-08-23): `az
// deployment group what-if` on the full `08-apps.bicep`/`params.dev.json` path
// returns **3 to create, 4 to modify**, and the 4 modifications are every
// running container app --
//
//   * `params.dev.json`'s `backendImage` names `acrinvoicellmdev.azurecr.io`, a
//     registry that does not exist (`az acr list` shows only `acrinvoicellmdev2`).
//   * `namingPrefix` is `invoice-llm` but the real environment was built
//     `invoicellm` (no hyphen), so a full deploy would rewrite every Key Vault
//     URI and managed identity reference to names that resolve to nothing.
//   * It would also roll back scale-rule changes applied live via
//     `az containerapp update`, never through this template.
//
// So this file does what the founder already did twice for this exact class of
// problem (`infra/agent-eval-job-only.bicep`, deleted 2026-08-23 along with the
// job it created when Feature 23 was rescoped; `infra/ops-digest-job-only.bicep`,
// same day): deploy the one new resource, over the same shared
// `modules/compute/scheduled-job.bicep`, with defaults that match what is
// **actually deployed** rather than what `params.dev.json` claims.
//
// This template creates exactly one resource and modifies none.
//
//   az deployment group what-if --resource-group rg-invoice-llm-dev \
//     --template-file infra/benchmark-eval-job-only.bicep
//   az deployment group create   --resource-group rg-invoice-llm-dev \
//     --template-file infra/benchmark-eval-job-only.bicep
//
// **Prerequisite that is not optional**: the backend image must already contain
// `benchmarks/` (this job imports `benchmarks.extraction.*`,
// `benchmarks.agent_eval_golden_sample`, `benchmarks.large_invoice_fixture`,
// `benchmarks.sage_seed_fixtures` -- see `docs/feature_23_ai_control_tower.md`'s
// "The cadence blocker" and its resolution) and `scripts/run_extraction_benchmark.py`
// / `scripts/run_agent_eval.py`. All four are new/moved as of 2026-08-23 and
// uncommitted at the time this file was written -- deploying before a CI build
// has pushed an image containing them produces a job whose every execution
// fails with `ModuleNotFoundError`, the exact failure this move exists to fix.
// `docker run --rm <image> python -c "import benchmarks.extraction.harness"`
// against the pushed image is the one-command check for this before deploying.
//
// Cost, stated plainly because this runs a real LLM every night: Track 1
// (`--mode live`, 9 documents) plus Track 2 (20 chat turns, separate judge)
// measured/extrapolated at roughly $0.10-$0.30/night at gpt-5-mini list price
// (see the feature doc's "Nightly scheduler as built" section for the
// measurement this is based on) -- small, but not zero, and it recurs every
// night indefinitely once deployed.
//
// Second caller as of 2026-08-24: `.github/workflows/deploy-dev.yml`'s
// `benchmark-gate` job starts an ON-DEMAND execution of this same job
// (`az containerapp job start --command/--args ...`) as the Feature 23
// pre-deploy gate, with the container command/args overridden for that one
// execution only -- a scoped-down verify-mode/5-case command, distinct from
// the `args` below, which is what the 03:00 UTC Schedule trigger still
// runs unmodified. This is why the job's identity needs Key Vault Secrets
// User + Cognitive Services User regardless of which caller is asking: the
// original inline-in-CI version of this gate (git history: fe021a3,
// reverted b1b9ff3) failed with ForbiddenByRbac because the GitHub Actions
// service principal tried to read AZURE-OPENAI-API-KEY itself and holds no
// Key Vault data-plane role -- running under this job's identity instead
// means that secret read never leaves Azure. See the `benchmark-gate` job's
// own header comment in deploy-dev.yml for the full design rationale
// (including why one job serves both callers instead of a second bicep
// file, and why `Schedule` triggerType -- not `Manual`/`Event` -- is
// correct for both).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource naming prefix. Defaults to `invoicellm` — the prefix this environment was ACTUALLY built with — not params.dev.json\'s `invoice-llm`, which resolves to Key Vault/identity/CAE names that do not exist here.')
param namingPrefix string = 'invoicellm'

@description('Registry holding the backend image. Defaults to the one registry that exists (`acrinvoicellmdev2`); params.dev.json still names `acrinvoicellmdev`, which does not.')
param acrName string = 'acrinvoicellmdev2'

@description('Backend image to run. Must be a build that contains benchmarks/, scripts/run_extraction_benchmark.py and scripts/run_agent_eval.py.')
param image string = 'acrinvoicellmdev2.azurecr.io/invoice-be:latest'

@description('Azure OpenAI deployment used by both tracks.')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Cron (UTC). 03:00 -- after caj-overdue-sweep-dev\'s 02:00, clear of caj-ops-digest-dev\'s 01/07/13/19:00 slots. Kept identical to 08-apps.bicep\'s benchmarkEvalCron; the two must not drift.')
param benchmarkEvalCron string = '0 3 * * *'

@description('Seconds before the execution is killed. See 08-apps.bicep\'s benchmarkEvalReplicaTimeout for the real measured/extrapolated runtime this is sized against.')
param benchmarkEvalReplicaTimeout int = 5400

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

// Identical parameter set to 08-apps.bicep's `benchmarkEvalJob` module -- see
// that file for the full rationale on each choice (--no-gate/--no-write/
// --tolerate-fp on Track 1, --paths default only, default judge mode on
// Track 2). If one is edited, the other must be -- they describe the same
// resource, and Container Apps will happily let a later Stage 8 deploy
// overwrite whatever this created.
module benchmarkEvalJob './modules/compute/scheduled-job.bicep' = {
  name: 'benchmark-eval-job-only-deploy'
  params: {
    location: location
    caeId: cae.id
    jobName: 'caj-benchmark-eval-${environment}'
    containerName: 'benchmark-eval'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    acrName: acrName
    image: image
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
    appInsightsConnectionString: appInsights.properties.ConnectionString
    cpu: '1.0'
    memory: '2.0Gi'
    replicaTimeout: benchmarkEvalReplicaTimeout
  }
}

output jobName string = benchmarkEvalJob.outputs.jobName
output jobId string = benchmarkEvalJob.outputs.jobId
