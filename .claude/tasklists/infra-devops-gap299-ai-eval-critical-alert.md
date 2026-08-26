# infra-devops — Gap 299: AI-eval "critical" finding alert path

Founder-approved task 5 of the Feature 20/23/24 completion list. Real implement + deploy, dev only, same ladder as Gaps 320/297.

## Steps

- [x] Read `.claude/CONVENTIONS.md` and `active-work.md` — no conflicting in-flight work found for this file set.
- [x] Read tracker Gap 299 entry (`be_features_tracker.md` line 928) — confirmed it still says `[ ]` and "blocked behind the same deploy as Gap 298." Confirmed stale per founder's framing (agent_eval_run has live rows already).
- [x] Read `feature_20_23_24_ops_workbook.md` blockers table — confirmed the `-critical`/`-info` action-group split is the one open item relevant here (three genuinely-open rows: SendGrid, `-critical` split, Stage 8). Verified live this claim is now partially stale too (see findings).
- [x] Read `services/ops_recommendation.py::evaluate_ai_improvement()` and `SCORE_BANDS` — got the exact red/yellow thresholds (pass_rate 0.20/0.30, faithfulness 0.70/0.85, relevance 0.85/0.95, accuracy 0.40/0.55, context 0.50/0.70, orchestration 0.60/0.80) and `MIN_GRADED_TURNS = 20`.
- [x] Read `telemetry.py::track_eval_result` (emits `agent_eval_run`) for exact field names: `pass`, `faithfulness_score`, `relevance_score`, `accuracy_score`, `context_score`, `orchestration_score`, `run_source`.
- [x] Traced `run_source` values: nightly/adhoc golden-bank runs tag `run_source="golden"` (`services/benchmark_artifacts.py::configure_run_source`), not "nightly" — confirmed live.
- [x] Read `infra/modules/monitoring/alert-rules.bicep`'s `dlqPoisonAlert` for house style on `Microsoft.Insights/scheduledQueryRules` (query/timeAggregation/threshold/failingPeriods/actions.actionGroups shape).
- [x] Read `infra/monitoring/ai_control_tower_workbook.json`'s Section D/G KQL for the exact `AppEvents | ... | extend d = parse_json(Properties)` pattern already proven live against this workspace.
- [x] Verified live via `az`: `ag-invoice-llm-dev` exists (email `application@infinevocloud.com` + Teams webhook). **Also found `ag-invoice-llm-dev-critical` and `ag-invoice-llm-dev-info` now exist live** (contradicts the task's stated caveat that `-critical` 404s) — flagged in chat, targeted `ag-invoice-llm-dev` per explicit instruction regardless.
- [x] Verified live via `az monitor log-analytics query`: `agent_eval_run` has 35 rows, all `run_source="golden"`, single batch (`TimeGenerated` ~03:36:27 on 2026-08-26). Computed live aggregate: pass_rate 0.257, faithfulness 0.797, relevance 0.974, accuracy 0.543, context 0.839, orchestration 0.870 — all yellow-or-green, no red-band crossing today.
- [x] Wrote `infra/alert-ai-eval-critical-only.bicep` — new standalone `Microsoft.Insights/scheduledQueryRules` (kind `LogAlert`) over `agent_eval_run`, `run_source=="golden"`, `MIN_GRADED_TURNS` guard, per-run (not trend) firing, wired to existing `ag-invoice-llm-dev`.
- [x] `az bicep build` — 0 errors.
- [x] `az deployment group what-if -g rg-invoice-llm-dev` — confirmed Create-only, exactly 1 resource (1 to create, 54 to ignore).
- [x] `az deployment group create` — first attempt with `evaluationFrequency: P1D` **failed live** ("Stateful rules can not run in a frequency greater than 12 hours" — `autoMitigate: true` requires ≤12h). Fixed to `evaluationFrequency: PT6H` (kept `windowSize: P1D`, `autoMitigate: true`), rebuilt, re-ran what-if (still 1 create/54 ignore), redeployed — `provisioningState: "Succeeded"`.
- [x] Pull-back proof — `az monitor scheduled-query show -g rg-invoice-llm-dev -n alert-agent-eval-run-critical-dev`: query/threshold/timeAggregation/evaluationFrequency/windowSize/kind/severity/actionGroups all match the template exactly.
- [x] Closure check — ran the alert's exact deployed KQL live via `az monitor log-analytics query`: 0 rows returned, i.e. would **not** fire today. Cross-checked with a manual aggregate of the same 35 live rows (pass_rate 0.257, faithfulness 0.797, relevance 0.974, accuracy 0.543, context 0.839, orchestration 0.870 — all yellow-or-green, none red).
- [x] Updated `be_features_tracker.md` Gap 299 → `[x]`, additive (original paragraph preserved, closure evidence appended below it).
- [x] Updated `feature_20_23_24_ops_workbook.md`'s `-critical` action-group blocker row — additive correction appended (found live during this task: `ag-invoice-llm-dev-critical`/`-info` now exist, contradicting the row's "404s live" wording, though the row's substantive "no Teams receiver" finding still holds). Flagged as unreconciled, out of scope for Gap 299.
- [x] Reported findings in chat (not `reports/infra/`).

## Final status
Done. New file `infra/alert-ai-eval-critical-only.bicep` deployed to `rg-invoice-llm-dev`, live, verified via all 4 rungs (build clean, what-if 1-create-only, provisioningState Succeeded, pulled-back live resource matches template). Alert would not fire on today's live data (no red-band crossing, several yellow, n=35≥20). Tracker Gap 299 closed `[x]`. One out-of-scope discrepancy found and documented, not fixed: `ag-invoice-llm-dev-critical`/`-info` action groups are live (contradicting prior "404s" docs), founder call needed on reconciling that.
