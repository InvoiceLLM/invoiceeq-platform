targetScope = 'resourceGroup'

// ============ Feature 26 Phase 1.4 (Gap 450): production-judge quality alert ============
//
// Why a separate file, again
// ----------------------------------------------------------------------------
// The same reason `alert-ai-eval-critical-only.bicep` is standalone: a Stage 9
// redeploy carries the known `params.dev.json` naming/image drift (Gap 298), and a
// what-if on Stage 8 would create a second Front Door. This template creates exactly
// one resource and touches nothing else.
//
// What this watches, and how it differs from the Gap 299 alert
// ----------------------------------------------------------------------------
// Gap 299's alert watches the NIGHTLY GOLDEN BANK (`run_source == "golden"`): a
// curated set of questions with reference answers, graded once a day. It cannot see a
// single real user being given a bad answer this afternoon.
//
// `services/online_quality_judge.py` already grades REAL turns as they happen and
// emits them on the same `agent_eval_run` event with `run_source == "production"` --
// and until this file, nothing alerted on those rows at all. That is the gap Feature
// 26's Phase 1 item 1.4 names: the scores exist and are visible on the AI Control
// Tower workbook's Section G panels, but a sustained drop pages nobody.
//
// Threshold: p95 vs the mean, deliberately
// ----------------------------------------------------------------------------
// The golden-bank alert averages, because a curated 20-question set is one sample of
// one system. Production traffic is not: averaging it lets a large number of easy
// "what did I spend?" turns hide a small number of badly-grounded ones, which are
// exactly the turns that cost trust. So this alert reads the 5th percentile of
// faithfulness -- the WORST end of the distribution -- and fires when even that band
// degrades, plus a mean guard for the case where the whole distribution slides.
//
// 0.80 is `SCORE_BANDS["faithfulness"]` red (0.70) plus a margin, because a
// production-judge score is reference-free: it grades whether the answer is supported
// by the evidence the turn actually retrieved, and an unsupported figure in a
// financial answer is worse than a merely unhelpful one. Stated as a parameter so the
// number can be tuned against real data without editing the query.
//
// Sample guard: `MIN_GRADED_TURNS` (20), the same constant
// `services/ops_recommendation.py` uses to decide when it has enough data to report a
// verdict rather than `insufficient_data`. Below it this alert stays silent rather
// than paging on three turns.
//
// `PT6H` evaluation frequency, not lower: Azure rejects a stateful
// (`autoMitigate: true`) log alert above 12h, and the Gap 299 deployment established
// PT6H/P1D as the pair this workspace accepts.

@description('Azure region for the scheduledQueryRules resource. Cannot be "global" -- must match the target resource group region.')
param location string = resourceGroup().location

@description('Log Analytics workspace the chat telemetry lands in.')
param logAnalyticsWorkspaceName string = 'law-invoicellm-dev'

@description('Existing action group to notify.')
param actionGroupName string = 'ag-invoice-llm-dev'

@description('Severity. 1 = error, matching the Gap 299 alert: a quality regression on live traffic is not a warning.')
param alertSeverity int = 1

@description('Below this p95 faithfulness over the window, fire. See the header for why this is above the golden-bank red band.')
param faithfulnessP95Below string = '0.80'

@description('Below this MEAN faithfulness over the window, fire regardless of the percentile.')
param faithfulnessMeanBelow string = '0.70'

@description('Minimum graded production turns in the window before any verdict is drawn. ops_recommendation.py::MIN_GRADED_TURNS.')
param minGradedTurns int = 20

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' existing = {
  name: actionGroupName
}

// One line, matching this repo's house style for scheduledQueryRules KQL.
// `percentile(faithfulness_score, 5)` is named `p95_worst` because it is the 5th
// percentile -- i.e. the score 95% of turns do better than. Naming it for what it
// guards against rather than for the arithmetic keeps the alert text readable.
var judgeQuery = 'let turns = AppEvents | where TimeGenerated > ago(1d) | where Name == "agent_eval_run" | extend d = parse_json(Properties) | where tostring(d.run_source) == "production" | extend faithfulness_score = todouble(d.faithfulness_score) | where isnotnull(faithfulness_score); turns | summarize turns = count(), p95_worst = percentile(faithfulness_score, 5), mean_faithfulness = avg(faithfulness_score) | where turns >= ${minGradedTurns} | extend crossed = pack_array(iff(p95_worst < ${faithfulnessP95Below}, strcat("p95_worst_faithfulness=", round(p95_worst,4)), ""), iff(mean_faithfulness < ${faithfulnessMeanBelow}, strcat("mean_faithfulness=", round(mean_faithfulness,4)), "")) | mv-expand crossed to typeof(string) | where crossed != "" | project crossed, turns, p95_worst, mean_faithfulness'

resource productionJudgeAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-production-judge-faithfulness-dev'
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: 'Gap 450: production-judge faithfulness degraded on live traffic'
    description: 'Fires when reference-free faithfulness on REAL user turns (agent_eval_run, run_source=="production", n>=20 in 24h) drops below 0.80 at the 5th percentile or below 0.70 on the mean. Complements alert-agent-eval-run-critical-dev, which watches only the nightly golden bank and cannot see a live user being given an unsupported figure. Closes Feature 26 Phase 1 item 1.4.'
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
          query: judgeQuery
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

output alertResourceId string = productionJudgeAlert.id
output alertName string = productionJudgeAlert.name
