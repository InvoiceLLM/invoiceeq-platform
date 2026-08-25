# Feature 20 / 23 / 24 — Ops Workbooks + Field Recommendations

Consolidated 2026-08-25. Replaces four docs, all deleted: `feature_20_observability_monitoring_alerts.md`,
`feature_23_ai_control_tower.md`, `feature_24_ops_digest_agent.md`, `feature_20_23_24_implementation_status.md`.
Feature numbers 20/23/24 are kept because the tracker, gap entries and code comments already use them.

The full build narrative for everything below lives in git history; this doc keeps only what is
still true and still load-bearing.

---

## Purpose

Two requirements, and nothing else:

1. **A comprehensive field review.** An agent goes over **every field on both workbooks** and writes,
   per field, what the value is, what it means, and a recommendation — how to cut cost, how to raise
   quality — or `NA` when the field is a config value / pure context. The output is surfaced back **on
   the Workbook itself**, not emailed or posted anywhere.
2. **Critical items keep alerting in real time, exactly as they do today.** Azure Monitor alert rules →
   the existing action groups → email/Teams. That path is pre-existing, works, and is **explicitly not
   in scope here** — it is not being redesigned, rerouted or wrapped.

Everything else that was previously scoped under Feature 24 (tiering, digests, delivery, synthesis
rubrics) is superseded — see "The digest build, superseded" below.

**Internal-only.** Same access boundary as the Azure Portal/Workbooks today; never customer-facing.

---

## What's built and verified

### The two workbooks — both deployed and live-verified

| Workbook | Definition | Bicep | Live resource | Status |
|---|---|---|---|---|
| Cost + Health/Performance (F20) | `infra/monitoring/cost_health_workbook.json` — 25 items | `infra/workbook-cost-health-only.bicep` | `618c81c7-353d-498a-93be-becc2e3e84cf` | Deployed 2026-08-24, `serializedData` pulled back via `az rest ...canFetchContent=true` and checked |
| AI Control Tower (F23) | `infra/monitoring/ai_control_tower_workbook.json` — 49 items, 40 KQL steps | `infra/workbook-ai-control-tower-only.bicep` | `c1168d95-73e2-49fb-8b56-5bff5cdb990a` | Deployed 2026-08-24, deployed JSON deep-compared to local: 49/49 items identical |

Both are **flat, single-page, no tabs, no `conditionalVisibility`, no `customWidth`** — that shape was
arrived at after tabs, the `tiles` big-number formatter and `customWidth` each caused a real rendering
failure on the earlier F23 builds. Both use `visualization: "tiles"` with `formatter: 8` threshold
coloring, `sourceId` = the raw `law-invoicellm-dev` workspace (so queries use
`AppEvents`/`Name`/`parse_json(Properties)`/`TimeGenerated`, **not** the App-Insights-classic
`customEvents`/`name`/`customDimensions` aliases). Every KQL/ARG query in both files was executed live
before being written in; both validate against Microsoft's published `schema/workbook.json` with 0 errors.

**Panel inventory — Cost + Health (25 items):** `shared-parameters`, `cost-header`, `cost-trend-budget`,
`cost-by-service`, `health-header`, `container-status`, `container-replicas`, `container-scale-config`,
`container-restarts`, `db-status-postgres`, `db-status-postgres-connections`,
`db-status-postgres-connection-util`, `db-status-postgres-liveness`, `db-status-redis`,
`db-status-redis-counts`, `db-status-redis-hit-ratio`, `db-status-redis-liveness`, `dlq-panel`,
`api-perf-header`, `api-perf-by-area`, `api-perf-error-rate`, `alerts-header`, `alerts-trend`,
`alerts-table`, `footer`.

**Panel inventory — AI Control Tower (49 items), 7 sections:**
A `a1`–`a6` (live model cost & latency), B `b1`–`b7` (chat-turn behaviour), C `c1`–`c4`
(sessions/threads), D `d1`–`d6` (golden bank), E `e1`–`e3` (extraction benchmark), F `f1`–`f2`
(online-eval signals), G `g1`–`g2` (production quality judge), plus `shared-parameters` (Subscription +
free-text `SessionId` drill-down), 7 section headers and a footer.

The field-by-field content of both is enumerated in the sample table below — that table **is** the field
inventory as well as the spec for the recommendation pass.

### Rules the workbooks already enforce — keep these

- **Data only, no commentary in a live tile.** Design rationale lives in docs, not in panel titles.
- **Minimum-sample guard** on every colored tile (n=20 turns/calls, n=3 runs) using the
  `cost-trend-budget` sentinel: `-1 → representation: "blue", text: "n/a — see Detail"`, with the real
  number still shown in `Detail` so the guard never hides that the panel is bound to live data.
- **Coloring must mean something.** Liveness/health string fields (`is_db_alive`,
  `geoReplicationHealthy`) get their own text-equality tiles — sharing a percent threshold column made
  `0`/"Down" render green. Counts with no status meaning (replicas, connection counts, cache hit/miss
  counts, request volume, cost) are blue by default; derived ratios (Postgres connection utilization %,
  Redis cache hit ratio %) are the colored ones.
- **`run_source` filtering.** Eval/benchmark traffic exports the same events and spans as production
  (`golden`/`predeploy` vs `production`), so any production-only view must filter on it.
- **No customer content in a workbook.** Section C's per-turn drill-down carries `message_id`,
  `trace_id`, `turn_id`, route, status, timing, `sql_attempts`, `tool_output_chars` — never
  `generated_sql` or real tool-output text, which a `chat_turn` event does carry.

### Azure Resource Graph / Azure Monitor data quirks — verified live, easy to get wrong

Confirmed against subscription `2ae37d8b-…` before any parsing code was written:

1. `properties.essentials.alertRule` is the **full resource ID**, not a friendly name — take the last segment.
2. `severity` is the string `"Sev2"`, not the integer `2`.
3. `monitorConditionResolvedDateTime` is `""` (**empty string, not null**) while an alert is still firing.
4. `alertState` (`New`/`Acknowledged`/`Closed`) is **not** whether the alert is over — that is
   `monitorCondition` (`Fired`/`Resolved`). Live rows are routinely `monitorCondition: Resolved` +
   `alertState: New` at the same time, because nobody clicks "close" in the portal. Reading `alertState`
   reports every self-resolved alert as still open. Pinned by
   `test_self_resolved_reads_monitor_condition_not_alert_state`.
5. **ARG does not return which action group an alert notified.** It has to be reconstructed from
   severity: Sev 0/1 → critical, Sev 2/3 → info. Not a guess — all 16 rules in `alert-rules.bicep` were
   read individually and the mapping holds without exception; the CAE resource-health activity-log
   alert carries no `severity` field at all and is special-cased by name.

### Other verified facts worth not re-deriving

- **`AppRequests` was empty for a Python import-order reason, now fixed.** `FastAPIInstrumentor`
  rebinds `fastapi.FastAPI`; `main.py` had already copied the original class into its namespace, so the
  app was built un-instrumented and no SERVER span ever existed. Fixed with the order-independent
  `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")`. `/health` is excluded on purpose
  (ACA probes would dominate volume). **Use `sum(ItemCount)`, never `count()`** — the distro defaults to
  `RateLimitedSampler{5.0}` and `ItemCount` is the sampling weight.
- **LLM calls now emit an `AppDependencies` row.** One `SpanKind.CLIENT` span per call from inside
  `tracked_llm_call()` (no call site changed), exported as `DependencyType = "GenAI | az.ai.openai"`,
  parented to the request span so "how much of this turn was the model?" is a join against `AppRequests`.
- **Cost Management API shapes.** The `forecast` endpoint **rejects `timeframe: MonthToDate`** (the
  `query` endpoint accepts it) — use `Custom` with explicit month bounds. Parse columnar responses **by
  column name, never position**; `UsageDate` arrives as the number `20260805`. Day-over-day compares
  days **-3 and -2, not -2 and -1** — the most recent usage day is always partial.
- **The budget is INR.** `budget-invoicellm-dev` was ₹150 with USD-shaped thresholds and permanently
  breached; fixed 2026-08-23 to ₹20,000/month with 50/75/95%-actual notifications. Any cost panel must
  read `currency` rather than assume USD.
- **Naming-prefix drift is real and load-bearing.** `params.dev.json` says `namingPrefix: "invoice-llm"`,
  but the environment was built with `invoicellm` (`kv-invoicellm-dev`, `id-invoicellm-dev`,
  `cae-invoicellm-dev`, `stinvoicellmdev2`). Names must be defaulted to the deployed value with an
  override, not derived.
- **KQL traps found live:** `latest` is a reserved word; `avg()` over an empty set returns `NaN` (not
  null) and renders literally, so guard with `iff(isnan(x), real(null), x)`; a bare `top 1 by … desc`
  returns **zero** rows over empty input, so "latest run" tiles use a `summarize`-based `arg_max` tuple,
  which emits exactly one (null-valued) row; `arg_max(timestamp, status)` mis-binds to the key column —
  use the tuple form `(last_ts, last_status) = arg_max(TimeGenerated, status)`.

### What is real data today vs. structurally empty

| Source | State |
|---|---|
| `llm_agent_call` (Section A) | Real production traffic |
| `agent_eval_summary` (Section D) | Real, one `predeploy` row — the n=3-run guard correctly shows the sentinel with the real number in Detail |
| `azure_cost_snapshot` / `azure_cost_slice` | Real, but from a sweep run predating the budget fix, and the sweep is **not scheduled** |
| `chat_turn` (Sections B, C) | 0 rows — the live backend image predates the commit that added it |
| `extraction_benchmark_run` (Section E) | 0 rows until the Gap 309 logging-level fix reaches a deployed image |
| `online_eval_signal` (Section F) | 0 rows on a schedule basis; `clarification_rate`/`budget_exhaustion_rate` are **permanently** degenerate as of Gap 316 (2026-08-25) — both read `stop_reason`/clarification state that only SAGE's deleted orchestrator ever produced, so they now measure nothing rather than measuring a flag that is off |
| `agent_eval_run` where `run_source == "production"` (Section G) | 0 rows |
| SAGE per-tool cost (`a6`), stop reasons (`b6`) | Structurally empty while the SAGE flag is off — stated on the panel, not omitted |

### The digest build, superseded

A two-tier (critical/digest) alerting-and-synthesis agent was built 2026-08-23 —
`services/ops_digest_routing.py`, `ops_digest_collect.py`, `ops_digest.py`, `ops_digest_delivery.py`,
`scripts/ops_digest_job.py`, 56 tests, a 6-hour scheduled-job template, LLM synthesis, self-resolved-item
compression, cross-item context, Common-Alert-Schema delivery to the receivers of the live action group.
It was never deployed, and on 2026-08-25 it was **superseded as over-scoped**: the requirement is one
recommendation pass rendered on the workbook, and critical alerting already exists. **The code was
deleted the same day** (Gap 311) — all four `services/ops_digest*.py` modules, `scripts/ops_digest_job.py`,
both test files, `infra/ops-digest-job-only.bicep`, the `opsDigestJob` module in `08-apps.bicep` and the
seven `OPS_DIGEST_*` settings. It and its full design record remain in git —
`git log -- Prod_Invoice_LLM/apps/invoice-be/services/ops_digest*.py` (commit `bce9e38`) — and are not
restated here. Two pieces of it were kept rather than deleted with the rest: the ARG quirks list, captured
above rather than in that code; and `emit_online_signals()`'s scheduled caller, extracted before the
deletion into **`scripts/emit_online_signals_job.py`** (`--window-hours` / `--dry-run` / `--json`), with
its coverage in `tests/test_emit_online_signals_job.py`. Like the digest job it came out of, that script
has no `Microsoft.App/jobs` resource yet, so Gap 305 stays `[~]` for exactly the same reason as before.
`Monitoring Reader` in `rbac-assignments.bicep` was also kept — it was added for the digest agent, but the
recommendation pass needs the same two ARM reads.

---

## Sample field-recommendation table

This is the worked example of what the recommendation pass must output — one row per workbook field:
value, explanation, recommendation-or-NA.

## Workbook 1: Cost + Health/Performance (Feature 20)

| Field | Sample Value | Explanation | Sample Recommendation |
|---|---|---|---|
| MTD spend % of budget | 62% (₹1.24L of ₹2L) | Month-to-date spend vs. budget | Trending >100% by month end → review top services for cuts |
| Budget amount | ₹2,00,000 | Configured monthly budget | NA — config value |
| Month-end forecast % | 118% | Projected month-end spend at current run-rate | Forecast >100% → recommend cost review before month end |
| Spend per service | Container Apps — ₹45,000 | Latest snapshot spend by Azure service | Highest-spend service with low utilization elsewhere → rightsizing candidate |
| CPU% (per app) | 18% | 1h avg CPU utilization | Persistently <20% → lower min replicas / scale-rule floor |
| Memory% (per app) | 72% | 1h avg memory utilization | Persistently >80% → raise memory limit, OOM risk |
| Replica count | 2 | 1h avg running replicas | Pinned at max → raise max; at min with low CPU → lower min |
| Running status | Running | Live resource state | Anything but Running → restart investigation |
| Restarts24h | 3 | Restart count, last 24h | Recurring → check crash logs/memory limits |
| Postgres CPU % | 35% | 6h avg Postgres CPU | Sustained >70% → scale tier up |
| Postgres Memory % | 55% | 6h avg Postgres memory | Sustained high → scale tier or optimize queries |
| Postgres Disk % | 41% | 6h avg storage used | Approaching 100% → storage increase/cleanup |
| Open connections | 12 | 6h avg active DB connections | NA unless near limit |
| Max connections | 100 | Configured limit | NA — config |
| Connection utilization % | 12% | active/max, 6h avg | Sustained >80% → connection pooling review |
| is_db_alive | Alive | 6h avg liveness check | "Down" → critical, already alerted |
| Redis server load % | 8% | 6h avg Redis load | Sustained high → Redis tier upgrade |
| Redis memory used % | 44% | 6h avg Redis memory | Approaching 100% → eviction policy review/tier upgrade |
| Connected clients | 6 | 6h avg | NA unless anomalous spike |
| Cache hits/misses | 4,200 / 300 | 6h avg counts | NA — feeds ratio below |
| Cache hit ratio % | 93% | hits/(hits+misses) | Low and dropping → review cache TTLs/invalidation |
| geoReplicationHealthy | Healthy | 6h avg replication health | "Unhealthy" → investigate replication lag |
| Poison messages isolated | 0 (7d) | DLQ isolation events | Any occurrence → root-cause the failing payload |
| Requests by feature area | Chat — 12,400 (30d) | Request volume per area | NA — volume context |
| P95 latency by area | Chat — 850 ms | 30d P95 latency per area | Elevated vs. other areas → prioritize profiling |
| Error rate by area | Chat — 0.4% | 30d error rate per area | Elevated → log review for that area |
| Alerts/day by severity | Sev2 — 4/day (14d) | Daily alert volume | Persistently noisy severity → alert-rule tuning |
| Alerts, last 24h | 2 | Rolling 24h count | NA — informational |

## Workbook 2: AI Control Tower (Feature 23)

| Field | Sample Value | Explanation | Sample Recommendation |
|---|---|---|---|
| Cost by agent (7d/30d) | query_agent — $12.40 / $52.10 | USD LLM cost per agent | Disproportionate to value → cheaper model / shorter prompts |
| Spend by run_source (7d) | production $80 · eval $15 | Cost split by traffic source | Eval spend growing vs. production → review benchmark frequency |
| Latency p50/p95 by agent | 900 / 2,100 ms | 30d latency percentiles | Wide p95-p50 gap → investigate slow-path calls/timeouts |
| Error rate by agent | trainer_agent — 1.2% | 30d % calls in error | Elevated → review agent failure logs |
| GenAI dependency p50/p95 | extraction_agent — 700/1500 ms | OTel span duration cross-check | Large gap vs. agent's own latency → check instrumentation |
| SAGE per-tool cost | — | Empty while flag off | NA — dormant |
| Outcome mix | success 91% · declined 3% · error 2% · cache_hit 4% | Turn outcome split, 30d | Rising declined/error → review routing/guardrails |
| chat_turn error rate | 1.8% | 30d turn error rate | Elevated → log/trace review |
| Zero-result rate | 6% | % turns returning nothing | Elevated → review RAG corpus/query coverage |
| Route mix | RAG 40% · SQL 45% · CHAT 15% | Routing split, 30d | Skew inconsistent with usage → review router thresholds |
| Turn latency p50/p95 | 1,100 / 3,200 ms | Excl. cache_hit, 30d | High p95 → investigate slow queries/tool calls |
| SQL avg attempts | 1.3 | Avg SQL-gen attempts/turn | High → improve SQL prompt/schema hints |
| SQL max attempts | 4 | Worst case | NA — diagnostic ceiling |
| SQL repair-loop rate % | 18% | % turns needing >1 attempt | High → prompt/schema fix; each retry costs another call |
| Stop reasons | — | Empty while SAGE off | NA — dormant |
| Avg citation_count | 2.1 | Citations/turn, 30d | Very low → review under-citation |
| Avg result_invoice_count | 3.4 | Invoices/turn, 30d | NA unless anomalous |
| p50 tool_output_chars | 850 | Median tool-output length | Very high → trim tool output, cut token cost |
| Completed sittings (14d) | 340 | Ended sessions | NA — volume |
| Single-turn share % | 55% | % one-turn sessions | High → users not getting answers in one turn |
| p50/p90 turns/sitting | 2 / 7 | Session depth | NA — informational |
| Abandonment rate % | 9% | % sessions ending badly | Elevated → review last-turn failures |
| Abandoned by reason | declined 12 · error 5 | Breakdown of abandonment cause | Concentrated reason → target that failure mode |
| Session/turn drill-down fields | session_id, trace_id, etc. | Row-level identifiers | NA — lookup/debug only |
| Golden bank pass rate | 87% | Latest eval overall pass rate | Below target → use soft-metric map to locate the drop |
| Faithfulness / Relevance / Accuracy / Context / Orchestration | 0.91 / 0.88 / 0.93 / 0.85 / 0.90 | Latest run mean scores | Drop → review context, routing, extraction, retrieval, or tool sequencing respectively |
| Persona (uncolored) | 0.80 | Mean persona-adherence | Drop → review persona wording (judgment call) |
| Cost per turn (USD) | $0.018 | Latest run avg cost/turn | Rising → review model/prompt cost |
| Median turn latency (uncolored) | 1,400 ms | Latest run median latency | NA — uncolored, informational |
| Trend/provenance fields | pass_rate, run_label, model_under_test, etc. | Historical trend + audit trail | NA — context for drift detection |
| Alert recall % | 78% | % true alerts flagged, extraction bench | Below ~80% → review extraction rules for misses |
| Clean false-positive rate % | 4% | % clean cases wrongly flagged | Rising → tighten alert-rule specificity |
| Confusion matrix (TP/FN/FP/TN) | 40/8/3/49 | Raw classification counts | NA — feeds recall/FP rate above |
| Recall/FP trend | time series | Historical drift trend | NA — trend context |
| Online-eval breached signals | faithfulness_drift ok · latency_p95 breached | Latest breach flag per signal | Any breached → investigate via soft-metric map |
| Per-signal detail | value, threshold, confidence, etc. | Signal computation detail | NA unless breached |
| Turns judged (30d) | 1,850 | Production judge volume | NA — no threshold |
| Production pass rate | 84% | % passing (faithfulness+relevance) | Below golden-bank rate → investigate prod-vs-eval gap |
| Production Faithfulness/Relevance | 0.89 / 0.86 | Mean prod scores | Drop → same soft-metric map |
| Accuracy/Context (NULL) | — | Not scored in combined mode | NA — structurally empty |
| Helpfulness/Completeness/Tone | 0.85 / 0.82 / 0.90 | Combined-judge-only dimensions | Drop → review completeness/tone vs. persona guidelines |

---

## Not yet built — the actual remaining scope

The prerequisite is **done** (2026-08-25, Gaps 308 + 317 — code-level; the image refresh it needs is
tracked as a deploy, in the blockers table below). Items (a)–(c) are **not started**: nothing today
produces or stores a per-field recommendation, and the table above exists only as a one-off message.
Design finalized 2026-08-25 (see "Open decisions" above); real Gap numbers are filed in
`be_features_tracker.md` once each item starts — (a) = Gap 318, (b) = Gap 319, (c) = Gap 320.

- `[x]` ~~**(prerequisite) Fix the nightly job's crash.**~~ **Fixed in code — Gaps 308 + 317.** The
  `FileNotFoundError` after all real work (`.dockerignore` strips `tests/` from the production image) was
  fixed on 2026-08-24 by `default_output_dir()` in `scripts/run_agent_eval.py` (Gap 308) and re-verified
  2026-08-25 against a real `docker build -f docker/Dockerfile.be` (Gap 317): the literal nightly argv
  `--paths default --run-label nightly`, no `--out`, all 35 cases, real model, real Postgres →
  `NIGHTLY_EXIT=0`, 35 rows persisted, output written to `/tmp/agent_eval_output.json`. Gap 317 also
  closed the caller-side half of the same failure class (`main()` creates `--out`'s parent directory), so
  adding an `--out` to the job later cannot reintroduce it. **One thing is still open, and it is a
  deploy, not a code fix**: the image the job runs (`acrinvoicellmdev2.azurecr.io/invoice-be:latest`,
  built 2026-08-24T09:08:22Z) predates the fix and contains no `default_output_dir` at all, so the 03:00
  UTC schedule keeps failing until a backend image refresh lands — the same pending refresh the blockers
  table below already carries for `chat_turn`/GenAI-span/`AppRequests`. The trigger is reliable in code;
  it becomes reliable in Azure with that deploy.
- `[ ]` **(a) The recommendation pass.** A step appended to the nightly job's own script (not a new
  scheduled resource): reads Track 1/2's just-produced eval results, queries current cost/health
  (reusing `azure_cost.py`), and for each of the three categories (container health, cost, AI
  improvement) either confirms "everything worked" or writes a recommendation.
- `[ ]` **(b) Somewhere to persist a run's recommendations.** New. Nothing today survives past a one-off
  message. A workbook can only read Log Analytics / App Insights / Resource Graph / ARM / ADX — **it
  cannot query Postgres** — so persistence has to land somewhere a workbook can query (the established
  pattern in this repo is a custom event mirror, i.e. one `AppEvents` row per category per run, the same
  way `agent_eval_run` and `online_eval_signal` are mirrored).
- `[ ]` **(c) A new Workbook panel that renders the persisted recommendations.** One panel, on both
  workbooks or on one of them — a grid of `Category | Status | Explanation | Recommendation` filtered to
  the latest run. Must obey the existing rules above: data only, minimum-sample guard, no customer content.

### Open decisions — closed 2026-08-25

1. ~~**Cadence.**~~ **Closed: event-triggered off the existing nightly benchmark-eval job's completion**
   (`caj-benchmark-eval-dev`, `0 3 * * *` UTC), not a new independent schedule. Most of this system's
   data has no discrete "record populated" event to hook (Azure Monitor/ARG metrics are live-queried,
   not inserted); `chat_turn` populates on every message, far too often to trigger a full review. The
   nightly job finishing is the one already-existing, infrequent, meaningful "new data landed" moment —
   the recommendation pass becomes a step appended to that job's own script, not a new scheduled resource.
2. ~~**Coverage per run.**~~ **Closed: check-and-flag, not an exhaustive per-field dump.** Three
   categories — **container health, cost** (Feature 20) and **AI improvement** (Feature 23 quality). For
   each: confirm "everything worked," or write a recommendation. Not every one of the ~90 fields gets a
   line every run.

---

## Known blockers carried forward

Verified as of 2026-08-24, still open (last row added 2026-08-25 under Gap 317):

| Blocker | Detail |
|---|---|
| ~~CI `benchmark-gate` step is broken~~ — **removed, not fixed** | The `-c` argument bug (`az containerapp job start --command /bin/sh -c` → `unrecognized arguments: -c`) is moot: 2026-08-25, the entire `benchmark-gate` job was deleted from `deploy-dev.yml` per a standing instruction that the CI/CD deploy pipeline must never execute tests or benchmarks, not even indirectly via an Azure-side job execution. `deploy-backend`/`deploy-worker` now depend only on `changes`. No CLI fix needed or wanted — see Gap 312 in `be_features_tracker.md`. The direct-ARM `az rest` workaround noted in the prior version of this row was never applied and should not be revived for this purpose. |
| `Monitoring Reader` RBAC not granted | Declared in `infra/modules/security/rbac-assignments.bicep`, never deployed. `id-invoicellm-dev` holds 5 roles, not this one (verified live). Without it, anything reading `alertsmanagementresources` returns zero alerts. A plain Stage 7 (`07-rbac.bicep`) redeploy fails first on the naming drift — its default prefix resolves to `stinvoicellmdev`, live is `stinvoicellmdev2`. Needs a `namingPrefix` override or a narrow-scoped standalone template. |
| SendGrid not wired | `ca-invoice-be-dev` lists 11 secrets and `sendgrid-key-secret` is **not** among them, though `invoice-be.bicep` declares it. Any email path raises `SENDGRID_API_KEY is not configured` until a deploy seeds it. |
| No Teams receiver on a `-critical` action group | `action-group.bicep` declares a `-critical` / `-info` split (Teams/Slack webhooks on `-critical` only, `-info` deliberately `webhookReceivers: []`). **That split is not deployed** — `ag-invoice-llm-dev-critical` 404s live. What exists is `ag-invoice-llm-dev` and `ag-invoicellm-dev`, both notifying the identical destinations: one email receiver (`application@infinevocloud.com`) and one webhook receiver `teams-alert-channel` pointing at a Power Automate flow with `useCommonAlertSchema: true`. Any future delivery/target decision must account for this — including that a Sev-based critical/info destination split does **not** exist today. |
| Stage 8 (`08-apps.bicep`) is unrunnable against dev | `params.dev.json`'s `backendImage` points at `acrinvoicellmdev.azurecr.io` — **that registry does not exist**, the real one is `acrinvoicellmdev2` — and its `namingPrefix: "invoice-llm"` rewrites every Key Vault secret URI and the identity to names that do not exist. A Stage 8 deploy would also roll back the live CPU/memory scale rules. Anything new must deploy through a narrow standalone template, the pattern `workbook-cost-health-only.bicep` / `workbook-ai-control-tower-only.bicep` / `benchmark-eval-job-only.bicep` already use. |
| Alert-rule fix pending deploy | `alert-rules.bicep`'s CPU/memory alerts gained a second `AllOf` criterion (`Replicas >= app.maxReplicas`) so they only fire once autoscale is genuinely maxed out. `az bicep build` clean, `what-if` Succeeded — **`az deployment group create` deliberately not run.** |
| `chat_turn` / GenAI-span / `AppRequests` fixes pending deploy | All three are code-complete and locally verified but the live backend image predates them, so Sections B/C stay at 0 rows and `AppDependencies` has no `GenAI | az.ai.openai` rows until a backend deploy lands (no longer blocked by `benchmark-gate` — that gate is removed as of 2026-08-25, see the row above). |
| Nightly eval job's `FileNotFoundError` fix pending the *same* deploy | Code-complete (Gap 308's `default_output_dir()`, 2026-08-24; re-verified and extended by Gap 317, 2026-08-25) and proven inside a real `Dockerfile.be` build — the literal nightly argv now exits 0 and writes `/tmp/agent_eval_output.json`. But `acrinvoicellmdev2.azurecr.io/invoice-be:latest` was built **2026-08-24T09:08:22Z**, ~4h before the fix commit, and reading `/app/scripts/run_agent_eval.py` inside it shows **no `default_output_dir` at all** — so `caj-benchmark-eval-dev` still fails at 03:00 UTC every night (all real work done, then the crash, recorded `Failed` under `retryLimit 0`) until an image refresh lands. Same deploy as the row above; nothing else is needed. |

---

## Tasks

- `[x]` Cost + Health/Performance workbook built, deployed, live-verified
- `[x]` AI Control Tower workbook built, deployed, live-verified (49/49 items byte-identical)
- `[x]` Telemetry sources behind both workbooks: Azure cost snapshot/slice, `AppRequests`, GenAI
      dependency span, `chat_turn`, `agent_eval_summary`/`agent_eval_run`, `extraction_benchmark_run`,
      `online_eval_signal`
- `[x]` Field-by-field review of both workbooks, with a sample recommendation per field (the table above)
- `[x]` **Decide cadence** — closed 2026-08-25: triggered off the nightly job's completion, not a new schedule
- `[x]` **Decide coverage** — closed 2026-08-25: check-and-flag across 3 categories (container health, cost, AI improvement), not an exhaustive per-field dump
- `[x]` **(prerequisite)** Fix the nightly job's `FileNotFoundError` crash — done in code (Gap 308 fixed
      the default output dir 2026-08-24; Gap 317 re-verified it against a real image build and closed the
      caller-supplied-`--out` half, 2026-08-25). Needs the pending backend image refresh to take effect live.
- `[ ]` **(a)** Build the recommendation pass as a step in the nightly job's script — not started
- `[ ]` **(b)** Persist each run's recommendations somewhere a workbook can query (not Postgres) — not started
- `[ ]` **(c)** Add the Workbook panel that renders the latest run's recommendations — not started
- `[x]` Unblock deploys: `benchmark-gate` removed from `deploy-dev.yml` entirely (2026-08-25, Gap 312) — not fixed, per standing rule that CI/CD must never execute tests/benchmarks
- `[ ]` Grant `Monitoring Reader` to `id-invoicellm-dev` via a narrow template — not started
- `[ ]` Deploy the pending backend image so Sections B/C and the GenAI dependency rows carry real data — not started
