targetScope = 'resourceGroup'

// ============ Gap 299: AI-eval "critical" finding alert path, and nothing else ============
//
// Why this file exists instead of a Stage 9 (`09-monitoring.bicep`) redeploy
// ----------------------------------------------------------------------------
// Same class of problem `workbook-cost-health-only.bicep` / `benchmark-eval-job-only.bicep`
// / `rbac-monitoring-cost-only.bicep` already solved: a full stage redeploy risks the
// known `params.dev.json` naming/image drift (Gap 298), so this narrow standalone
// template creates exactly one resource -- a Log Analytics scheduled query alert rule --
// and touches nothing else.
//
// Tracker background (`be_features_tracker.md` Gap 299)
// ----------------------------------------------------------------------------
// Feature 23 emits AI-eval quality signals but, until this file, no Azure Monitor alert
// of any kind watches them -- a "critical" finding (a sharp quality drop) pages nobody.
// The tracker entry's original "blocked behind the same deploy as Gap 298" reasoning is
// stale: `agent_eval_run` already has live rows in `law-invoicellm-dev` (confirmed via
// `az monitor log-analytics query` on 2026-08-26: 35 rows, all `run_source == "golden"`,
// one batch from the nightly job), so this alert can be built against real data today.
//
// Threshold source -- reused, not invented
// ----------------------------------------------------------------------------
// Every default below is copied verbatim from `services/ops_recommendation.py`'s
// `SCORE_BANDS` dict and `MIN_GRADED_TURNS` constant (Category 3 / AI improvement,
// the same numbers Gap 318's recommendation-pass panel and the AI Control Tower
// workbook's D1-D3 tiles already use) -- so the alert and the live panels can never
// disagree about what "critical" means:
//   pass_rate     red < 0.20   (SCORE_BANDS["pass_rate"])
//   faithfulness  red < 0.70   (SCORE_BANDS["faithfulness"])
//   relevance     red < 0.85   (SCORE_BANDS["relevance"])
//   accuracy      red < 0.40   (SCORE_BANDS["accuracy"])
//   context       red < 0.50   (SCORE_BANDS["context"])
//   orchestration red < 0.60   (SCORE_BANDS["orchestration"])
//   minimum sample: 20 graded turns (MIN_GRADED_TURNS) -- below this, ops_recommendation.py
//   itself reports `insufficient_data`, not a graded verdict, so this alert applies the
//   same guard rather than judging a too-small sample.
//
// Event / field names -- verified against telemetry.py, not guessed
// ----------------------------------------------------------------------------
// `agent_eval_run` (`telemetry.EVAL_RESULT_EVENT_NAME`, emitted by
// `telemetry.track_eval_result()`) is one row per graded turn, carrying `pass` (0/1),
// `faithfulness_score`, `relevance_score`, `accuracy_score`, `context_score`,
// `orchestration_score` and `run_source`. `agent_eval_summary` (one row per whole run)
// was considered instead -- it is what the workbook's Section D golden-bank tiles read --
// but it has only 1 live row as of 2026-08-24 (a `predeploy` run), so it cannot be used
// for a real alert today; `agent_eval_run` has real nightly data and is what this repo's
// own Section G production-judge panels already query the same way (see
// `infra/monitoring/ai_control_tower_workbook.json`'s `g1-*` panels for the exact
// `AppEvents | ... | extend d = parse_json(Properties)` pattern this query reuses).
//
// `run_source` values are `production` / `golden` / `predeploy`
// (`telemetry.RUN_SOURCE_*`) -- there is no `"nightly"` value on this per-turn event.
// `services/benchmark_artifacts.py::configure_run_source()` maps both `--run-label
// nightly` and `--run-label adhoc` to `run_source = "golden"` (only `predeploy` gets its
// own value), so filtering on `run_source == "golden"` is the correct way to select the
// nightly job's (and any ad-hoc golden-bank run's) turns -- confirmed live: all 35
// current `agent_eval_run` rows carry `run_source = "golden"`.
//
// Per-run, not a trend -- reasoning
// ----------------------------------------------------------------------------
// `agent_eval_run` only gets new rows once a day (the nightly job), so a multi-run trend
// requirement would delay a real critical finding by days for no benefit; Gap 318's own
// recommendation pass already does per-run check-and-flag with no trend requirement, and
// this alert matches that. `windowSize` is `P1D` (looks back exactly one day) so each
// evaluation sees at most one nightly batch -- confirmed live, all 35 rows for the
// 2026-08-26 run landed within the same ~11ms window, so a 1-day window cannot blend two
// different runs together under the real nightly cadence. `evaluationFrequency` is
// `PT6H`, not also `P1D`: Azure rejects a stateful (`autoMitigate: true`) log alert with
// `evaluationFrequency` above 12h ("Stateful rules can not run in a frequency greater than
// 12 hours" -- hit live while deploying this file, not assumed). `autoMitigate: true` is
// kept (self-resolves once a later run clears the red band, and Azure's stateful model
// only notifies on a fired/resolved *transition* -- not on every 6h re-evaluation of an
// unchanged 24h window) so re-checking 4x/day against the same run does not mean 4
// separate pages for the same finding.
//
// Action group -- explicitly out of scope: no `-critical`/`-info` split deployment here.
// Targets the existing `ag-invoice-llm-dev` action group (verified live via
// `az monitor action-group list -g rg-invoice-llm-dev`), matching Gap 291's shared-channel
// decision. NOTE (2026-08-26, found while verifying the action-group name for this file):
// `ag-invoice-llm-dev-critical` and `ag-invoice-llm-dev-info` are now *also* live in this
// resource group (confirmed via `az monitor action-group show`), which contradicts the
// tracker/workbook's current "the `-critical` split is not deployed, 404s live" wording --
// that discrepancy is unrelated to this gap and is not resolved here; per the approved
// scope this file still targets `ag-invoice-llm-dev` only.

@description('Azure region for the scheduledQueryRules resource. Cannot be "global" -- must match the target resource group region, same constraint alert-rules.bicep documents for queryAlertLocation.')
param location string = resourceGroup().location

@description('Log Analytics workspace name this alert queries. Defaults to the live dev workspace.')
param logAnalyticsWorkspaceName string = 'law-invoicellm-dev'

@description('Action group to notify. Defaults to the existing ag-invoice-llm-dev (verified live 2026-08-26) -- deliberately NOT the -critical/-info split, out of scope for Gap 299.')
param actionGroupName string = 'ag-invoice-llm-dev'

@description('Alert severity. 1 matches this repo\'s house style for always-critical alerts (DLQ poison message, Key Vault availability, backend 5xx storms).')
param alertSeverity int = 1

@description('Minimum graded turns in the lookback window before a verdict is judged at all. Copied from services/ops_recommendation.py::MIN_GRADED_TURNS -- below this, the run is insufficient-data, not a graded pass/fail, and must not fire.')
param minGradedTurns int = 20

@description('Red-band lower bound for pass_rate. Copied from ops_recommendation.py SCORE_BANDS["pass_rate"][0].')
param passRateRedBelow string = '0.20'

@description('Red-band lower bound for faithfulness. Copied from ops_recommendation.py SCORE_BANDS["faithfulness"][0].')
param faithfulnessRedBelow string = '0.70'

@description('Red-band lower bound for relevance. Copied from ops_recommendation.py SCORE_BANDS["relevance"][0].')
param relevanceRedBelow string = '0.85'

@description('Red-band lower bound for accuracy. Copied from ops_recommendation.py SCORE_BANDS["accuracy"][0].')
param accuracyRedBelow string = '0.40'

@description('Red-band lower bound for context. Copied from ops_recommendation.py SCORE_BANDS["context"][0].')
param contextRedBelow string = '0.50'

@description('Red-band lower bound for orchestration. Copied from ops_recommendation.py SCORE_BANDS["orchestration"][0].')
param orchestrationRedBelow string = '0.60'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' existing = {
  name: actionGroupName
}

// One line, matching alert-rules.bicep's dlqPoisonAlert house style (no bicep
// multi-line strings used elsewhere in this repo's scheduledQueryRules). Semicolons
// separate the `let`/pipeline statements -- KQL does not require newlines.
var evalCriticalQuery = 'let turns = AppEvents | where TimeGenerated > ago(1d) | where Name == "agent_eval_run" | extend d = parse_json(Properties) | where tostring(d.run_source) == "golden" | extend passed = toint(d.pass), faithfulness_score = todouble(d.faithfulness_score), relevance_score = todouble(d.relevance_score), accuracy_score = todouble(d.accuracy_score), context_score = todouble(d.context_score), orchestration_score = todouble(d.orchestration_score); turns | summarize turns = count(), pass_rate = avg(todouble(passed)), faithfulness = avg(faithfulness_score), relevance = avg(relevance_score), accuracy = avg(accuracy_score), context = avg(context_score), orchestration = avg(orchestration_score) | where turns >= ${minGradedTurns} | extend crossed = pack_array(iff(isnotnull(pass_rate) and pass_rate < ${passRateRedBelow}, strcat("pass_rate=", round(pass_rate,4)), ""), iff(isnotnull(faithfulness) and faithfulness < ${faithfulnessRedBelow}, strcat("faithfulness=", round(faithfulness,4)), ""), iff(isnotnull(relevance) and relevance < ${relevanceRedBelow}, strcat("relevance=", round(relevance,4)), ""), iff(isnotnull(accuracy) and accuracy < ${accuracyRedBelow}, strcat("accuracy=", round(accuracy,4)), ""), iff(isnotnull(context) and context < ${contextRedBelow}, strcat("context=", round(context,4)), ""), iff(isnotnull(orchestration) and orchestration < ${orchestrationRedBelow}, strcat("orchestration=", round(orchestration,4)), "")) | mv-expand crossed to typeof(string) | where crossed != "" | project crossed, turns, pass_rate, faithfulness, relevance, accuracy, context, orchestration'

resource aiEvalCriticalAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-agent-eval-run-critical-dev'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: 'Gap 299: AI-eval nightly run crossed a red-band quality threshold'
    description: 'Fires when the nightly/ad-hoc golden-bank agent_eval_run batch (run_source=="golden", n>=20 graded turns) has any of pass_rate<0.20, faithfulness<0.70, relevance<0.85, accuracy<0.40, context<0.50, orchestration<0.60 -- the exact red bands services/ops_recommendation.py::SCORE_BANDS already uses for the AI Control Tower workbook. Closes tracker Gap 299: until this alert, a critical AI-eval finding paged nobody.'
    severity: alertSeverity
    enabled: true
    scopes: [
      logAnalytics.id
    ]
    evaluationFrequency: 'PT6H'
    windowSize: 'P1D'
    autoMitigate: true
    criteria: {
      allOf: [
        {
          query: evalCriticalQuery
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

output alertResourceId string = aiEvalCriticalAlert.id
output alertName string = aiEvalCriticalAlert.name
