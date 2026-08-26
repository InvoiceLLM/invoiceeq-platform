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
| Cost + Health/Performance (F20) | `infra/monitoring/cost_health_workbook.json` — 25 → **27 items** (Gap 320, 2026-08-26) | `infra/workbook-cost-health-only.bicep` | `618c81c7-353d-498a-93be-becc2e3e84cf` | Deployed 2026-08-24; re-deployed 2026-08-26 for Gap 320's recommendation panel, `serializedData` pulled back via `az rest ...canFetchContent=true` and deep-compared: 27/27 items identical |
| AI Control Tower (F23) | `infra/monitoring/ai_control_tower_workbook.json` — 49 → **51 items**, 41 KQL steps (Gap 320, 2026-08-26) | `infra/workbook-ai-control-tower-only.bicep` | `c1168d95-73e2-49fb-8b56-5bff5cdb990a` | Deployed 2026-08-24; re-deployed 2026-08-26 for Gap 320's recommendation panel (Section H), deployed JSON deep-compared to local: 51/51 items identical |

Both are **flat, single-page, no tabs, no `conditionalVisibility`, no `customWidth`** — that shape was
arrived at after tabs, the `tiles` big-number formatter and `customWidth` each caused a real rendering
failure on the earlier F23 builds. Both use `visualization: "tiles"` with `formatter: 8` threshold
coloring, `sourceId` = the raw `law-invoicellm-dev` workspace (so queries use
`AppEvents`/`Name`/`parse_json(Properties)`/`TimeGenerated`, **not** the App-Insights-classic
`customEvents`/`name`/`customDimensions` aliases). Every KQL/ARG query in both files was executed live
before being written in; both validate against Microsoft's published `schema/workbook.json` with 0 errors.

**Panel inventory — Cost + Health (27 items):** `shared-parameters`, `cost-header`, `cost-trend-budget`,
`cost-by-service`, `health-header`, `container-status`, `container-replicas`, `container-scale-config`,
`container-restarts`, `db-status-postgres`, `db-status-postgres-connections`,
`db-status-postgres-connection-util`, `db-status-postgres-liveness`, `db-status-redis`,
`db-status-redis-counts`, `db-status-redis-hit-ratio`, `db-status-redis-liveness`, `dlq-panel`,
`api-perf-header`, `api-perf-by-area`, `api-perf-error-rate`, `alerts-header`, `alerts-trend`,
`alerts-table`, **`ops-recommendations-header`, `ops-recommendations`** (Gap 320), `footer`.

**Panel inventory — AI Control Tower (51 items), 8 sections:**
A `a1`–`a6` (live model cost & latency), B `b1`–`b7` (chat-turn behaviour), C `c1`–`c4`
(sessions/threads), D `d1`–`d6` (golden bank), E `e1`–`e3` (extraction benchmark), F `f1`–`f2`
(online-eval signals), G `g1`–`g2` (production quality judge), **H `h1-ops-recommendations`
(the recommendation-pass grid, Gap 320)**, plus `shared-parameters` (Subscription + free-text
`SessionId` drill-down), 8 section headers (`section-a-header` … `section-h-header`) and a footer.

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
  read `currency` rather than assume USD. **Confirmed live 2026-08-26** by reading `budget-invoicellm-dev`
  with `az`: ₹20,000/month, notifications at 50/75/95% of *actual*. This sentence was right and
  `be_features_tracker.md`'s **Gap 295** was wrong — that gap sat at `[ ]` "not fixed here" until the
  2026-08-26 doc-reconciliation pass closed it against this evidence. One thing neither doc claimed and
  which is worth a founder decision rather than a silent edit: ₹20,000 is *below* the ~₹24,600 month-end
  forecast recorded in Gap 295 itself, so the 50% and 75% thresholds will likely fire every month.
- **Naming-prefix drift is real and load-bearing.** `params.dev.json` says `namingPrefix: "invoice-llm"`,
  but the environment was built with `invoicellm` (`kv-invoicellm-dev`, `id-invoicellm-dev`,
  `cae-invoicellm-dev`, `stinvoicellmdev2`). Names must be defaulted to the deployed value with an
  override, not derived.
- **KQL traps found live:** `latest` is a reserved word; `avg()` over an empty set returns `NaN` (not
  null) and renders literally, so guard with `iff(isnan(x), real(null), x)`; a bare `top 1 by … desc`
  returns **zero** rows over empty input, so "latest run" tiles use a `summarize`-based `arg_max` tuple,
  which emits exactly one (null-valued) row; `arg_max(timestamp, status)` mis-binds to the key column —
  use the tuple form `(last_ts, last_status) = arg_max(TimeGenerated, status)`. **`title` is also a
  reserved word** (Gap 320, 2026-08-26): `tostring(d.title)` fails with `SYN0002` (`could not be parsed
  at 'title'`) even inside a dot-property accessor on a `dynamic` — confirmed with the minimal live
  repro `print x = todynamic('{"title":"a"}').title`. Bracket notation sidesteps it:
  `tostring(d["title"])` parses and executes cleanly.

### The golden bank's tiers, and the multi-turn one added 2026-08-26 (Gap 307)

Added additively — nothing above changes. Track 2's nightly run is now **two tiers in one process**,
reported as **two summary buckets** rather than one:

| Bucket (`summary` key / event `path`) | What it holds | Scored dimensions |
|---|---|---|
| `default` | The 35 single-turn cases — 20 base-tenant + Wave 3's 15 India/US/EU | The nine that already existed |
| `default-multiturn` | Gap 307's 5 scripted conversations, 12 turns, 7 of them drift-scored | The same nine **plus `context_drift`** |

Four things about it that are decisions, not details:

- **Two buckets, not one, and this is the whole reason the tier is safe to add.** `summarise()` keys
  by path and `evaluate_ai_improvement()` reads `summary["default"]`. Folding twelve deliberately
  harder turns into that bucket would move the nightly pass rate and every quality mean onto a
  different population than every historical figure in this doc — a trend redefined halfway through.
  The constant is `services/benchmark_artifacts.py::MULTI_TURN_PATH`.
- **`context_drift` is deterministic, not a fourth judge call.** `services/agent_eval.py::
  score_context_drift()` scores *checks passed / checks pinned* against a `DriftExpectation` the
  golden script authored — forbidden entities (in the prose, or in the generated SQL, which is where
  Gap 276's surviving predicate shows up), required entities, and forbidden fetched invoice rows.
  It is a component-level score like `context`/`orchestration`: recorded and trended, **not** in
  `decide_pass()`.
- **No new event, no new resource, no bicep.** The tier rides the existing per-path
  `agent_eval_summary` mechanism (built for `default`/`sage`), so it emits a second event of an
  existing type; `context_drift_score` rides `agent_eval_run`'s `**extra_attributes` the same way
  Track 2's helpfulness/completeness/tone already do. There is deliberately **no drift tile** on
  either workbook yet — adding one is a workbook deploy and was out of scope.
- **The recommendation pass grades it on `d3-context`'s band, not a new one.** Every threshold in
  `services/ops_recommendation.py` is a live tile's, pinned by test. Drift is a retrieval failure, so
  it borrows the context tile's `(0.50 red, 0.70 yellow)` rather than inventing an uncalibrated pair
  — see `CONTEXT_DRIFT_BAND_KEY`. It is exempt from the n=20 sample guard, and that is stated in
  code: the tier is a fixed, exhaustive, deterministic script set run identically every night, so
  there is no sampling error for the guard to protect against, and applying it would disable the
  tier permanently.

**Offline only.** A live judge over production `chat_turn` events is explicitly *not* built and is
recommended as its own gap in `be_features_tracker.md` — judging live traffic is a product decision
of the same class as Gap 304 half 2, not a wiring change.

### What is real data today vs. structurally empty

| Source | State |
|---|---|
| `llm_agent_call` (Section A) | Real production traffic |
| `agent_eval_summary` (Section D) | Real, one `predeploy` row — the n=3-run guard correctly shows the sentinel with the real number in Detail |
| `azure_cost_snapshot` / `azure_cost_slice` | Real, but from a sweep run predating the budget fix, and the sweep is **not scheduled** |
| `chat_turn` (Sections B, C) | **Real data as of 2026-08-26.** ~~0 rows — the live backend image predates the commit that added it~~ — **Correction 2026-08-26 (live-Azure-verified):** that image refresh landed. The backend image was rebuilt **2026-08-25T14:41Z from commit `cb96d8f`**, and `AppEvents` in `law-invoicellm-dev` now returns real `chat_turn` rows, so Sections B and C render live production turn behaviour instead of empty panels. (`AppDependencies` gained its `GenAI`/`az.ai.openai` dependency rows and `AppRequests` gained rows from the real container in the same refresh — see the blockers table below.) |
| `extraction_benchmark_run` (Section E) | **Real data as of 2026-08-26.** ~~0 rows until the Gap 309 logging-level fix reaches a deployed image~~ — **Correction 2026-08-26 (live-Azure-verified):** same refresh. `cb96d8f` carries Gap 309's logging-level fix *and* Gaps 308/317's nightly-crash fix, and `caj-benchmark-eval-dev`'s **2026-08-26T03:00 UTC run succeeded**, so Track 1's recall/false-positive figures now reach Section E from a real scheduled execution rather than a developer's laptop. |
| `online_eval_signal` (Section F) | 0 rows on a schedule basis; `clarification_rate`/`budget_exhaustion_rate` are **permanently** degenerate as of Gap 316 (2026-08-25) — both read `stop_reason`/clarification state that only SAGE's deleted orchestrator ever produced, so they now measure nothing rather than measuring a flag that is off. **Correction 2026-08-26 (Gap 305 investigation, code-verified):** that is right for `budget_exhaustion_rate` and **wrong for `clarification_rate`** — only the latter's three `offline_*` `detail` keys read the dead notes; its headline `value`/`numerator`/`denominator` come from `looks_like_clarification()` over `chat_message` assistant rows and never had a SAGE dependency, so it still measures real traffic and must not be dropped on the strength of the sentence above. `budget_exhaustion_rate` is genuinely unfixable (its numerator *and* denominator are `stop_reason=` fragments `scripts/run_agent_eval.py` no longer writes, and `MAX_TOOL_CALLS`/`tool_call_budget_exhausted` exist in zero live code files) — retiring it is a founder decision, tracked on Gap 305 |
| `agent_eval_run` where `run_source == "production"` (Section G) | 0 rows. **Update 2026-08-26:** the reason moves from "flag off" to "flag now on, no real turn scored yet" — `ENABLE_PRODUCTION_QUALITY_JUDGE` was `False` in `config.py` with no bicep/env-var override anywhere, confirmed by a repo-wide grep of `Prod_Invoice_LLM/infra/`. Set live on `ca-invoice-be-dev` (`az containerapp update --set-env-vars ENABLE_PRODUCTION_QUALITY_JUDGE=true`, new revision `ca-invoice-be-dev--0000087`, confirmed `Healthy`/`Running`), and also declared through `08-apps.bicep` → `invoice-be.bicep` (default `false`) with `params.dev.json` overriding to `true` for dev only, so a future full Stage 8 deploy stays consistent instead of silently reverting the live CLI change. `az containerapp show` confirms the env var is present with value `true`. No real production `agent_eval_run` row has landed yet as of this edit — that requires a real authenticated chat turn against `ca-invoice-be-dev`, which this agent cannot generate itself (backend ingress is internal-only; a real Clerk-authenticated session is needed) — founder follow-up to generate one turn and re-check this row. See Gap 304 in `be_features_tracker.md` for the full mechanism note. |
| `ops_recommendation` (Gap 319, the recommendation pass; rendered by Gap 320's panel) | 0 rows, confirmed live 2026-08-26 via the deployed panel's own query against `law-invoicellm-dev`. It emits only from a `--run-label nightly` run, and the nightly job's image predates both Gap 318 and Gap 319 — same pending backend image refresh as the rows above. Nothing is wrong with the emitter or the panel; there has been no nightly execution carrying it yet. **Clarification 2026-08-26 (doc-reconciliation pass):** this row is **still correct and stays "structurally empty"** — but "same pending backend image refresh as the rows above" no longer parses now that those rows are corrected to *real data*, so state it directly: the 2026-08-25T14:41Z image (`cb96d8f`) carries Gaps 308/309/317 and therefore fixed `chat_turn` / `AppRequests` / GenAI spans / the nightly crash, but Gaps **318 and 319 are uncommitted** and no image contains them. `ops_recommendation` therefore needs a **further, distinct** image refresh — not the one that already landed. The 2026-08-26T03:00 nightly run succeeded without emitting any, which is the expected behaviour, not a regression. **Correction 2026-08-26 (redesign session, later the same day): this row is now closed — it no longer belongs under "structurally empty".** Gaps 318/319/320 are committed (`f9aa0c5`) and deployed, and the nightly run has produced **real `ops_recommendation` rows**, so both recommendation panels render live data. The commit state is verified in this repo; the "real rows landed" half is the founder's own observation from the 2026-08-26 design session and is recorded on that basis, not on a query run by this agent |
| SAGE per-tool cost (`a6`), stop reasons (`b6`) | Structurally empty while the SAGE flag is off — stated on the panel, not omitted. **Correction 2026-08-26 (Gap 305 investigation): this is now wrong for `b6` and its own panel text is wrong live.** There is no SAGE flag — Gap 316 deleted `ENABLE_AGENTIC_SAGE` outright — and `b6-stop-reasons` queries `chat_turn`'s `stop_reason`, which `agents/query_agent.py` populates on the **default** route (`sql_attempts_exhausted`, `sql_declined`, `sql_summary_failed`, `rag_answer_failed`, `chat_answer_failed`, `route_override_followup`), plus `agent_raised` from `routers/chat.py` and `queue_handler_raised` from `queue_worker/handlers.py`. `chat_turn` has carried real production rows since the 2026-08-25T14:41Z image, so `b6` is **real data**, not structurally empty — while the deployed tile still hard-codes `Detail = "SAGE-only field — structurally empty while ENABLE_AGENTIC_SAGE=false"`, i.e. it tells a reader that live data is empty. `a6` is untouched by this and remains genuinely dead (per-tool cost of tools that no longer exist). Not changed here — the workbook JSON is infra scope; raised on Gap 305 for a founder/infra call |

**One further deployed-panel finding from the same pass, also not changed (infra scope, Gap 305):** `f1-breached-signals` computes `Status = iff(latest_breached == "1", "breached", "ok")`. It keys off the event's `breached` flag alone and never inspects `value`, so a signal whose denominator is permanently 0 — which is exactly `budget_exhaustion_rate`'s state after Gap 316 — renders a **green "ok"** tile forever. That is the precise failure mode `services/online_eval_signals.py::SignalResult`'s docstring exists to prevent ("'Nothing happened' and 'nothing went wrong' are different facts and a dashboard that conflated them would show a healthy green on the day ingestion stopped"). The emitter honours the contract by sending `value=None`; the tile reads the wrong field. Whether this is fixed by retiring the signal, by adding an explicit unmeasurable state to the event, or by teaching F1 to render a null `value` as "not measured" is a founder call — all three are live options and none was taken unilaterally.

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

**Addendum 2026-08-26 (Gap 314) — the deletion list above is now complete.** Gap 311 left two artifacts
behind, deliberately flagged rather than swept in: `telemetry.py::track_ops_digest_run()` and
`OPS_DIGEST_EVENT_NAME` (the `ops_digest_run` custom event). Both were deleted on 2026-08-26 after a
repo-wide grep confirmed zero callers and zero tests, and — relevant to *this* doc rather than just to the
tracker — the same grep over `.json`/`.kql` confirmed **no workbook panel or saved query anywhere reads
`ops_digest_run`**, so no panel on either workbook lost a data source. The event never carried a row in the
first place: the job that would have emitted it (`caj-ops-digest-dev`) was never deployed, so
`ops_digest_run` is absent from `law-invoicellm-dev` historically as well as going forward, and it belongs
in neither the empty-panels table above nor any future one.

---

## Sample field-recommendation table

This is the worked example of what the recommendation pass must output — one row per workbook field:
value, explanation, recommendation-or-NA.

**Read this as the judgement spec, not the output schema.** The coverage decision closed the same day
(and built as Gap 318) is check-and-flag: a run emits three category verdicts, each naming only the
fields that were actually outside their band. This table is what supplied the *reasoning* for each of
those fields, plus the proof that every field on both workbooks can be reasoned about at all — it is
not what one run prints.

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
| Context drift (added 2026-08-26, Gap 307) | 0.96 | Mean over the multi-turn tier's drift turns only — **not on a workbook tile yet**, carried on the `agent_eval_summary` event whose `path` is `default-multiturn` | Drop → a scripted conversation lost or kept the wrong subject; the run artifact's drift note names the leaked/lost entity, and the code is `get_chat_history()` / `get_prior_turn_sql()` |
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
tracked as a deploy, in the blockers table below). **(a) is done** (2026-08-25, Gap 318 — code-level;
it rides into Azure on the same pending image refresh, and its container-health half additionally needs
the undeployed `Monitoring Reader` grant in the blockers table before it can read anything live).
**(b) is done** (2026-08-25, Gap 319 — code-level; it rides into Azure on that same image refresh), so a
run's three category verdicts now survive as `ops_recommendation` custom events. **(c) is done**
(2026-08-26, Gap 320 — deployed): a plain-grid panel on both workbooks now renders the latest run,
currently 0 rows for the same pending-image reason as (a)/(b). Design finalized 2026-08-25 (see "Open
decisions" above); Gap numbers in `be_features_tracker.md` — (a) = Gap 318, (b) = Gap 319, (c) = Gap 320.

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

  **Correction 2026-08-26 (doc-reconciliation pass, live-Azure-verified): that deploy landed, so the "one
  thing still open" above is closed.** The backend image was rebuilt **2026-08-25T14:41Z from commit
  `cb96d8f`**, which does contain `default_output_dir()`, and **`caj-benchmark-eval-dev`'s 2026-08-26T03:00
  UTC execution succeeded**. The nightly job is therefore reliable in Azure and not only in code, which also
  means the cadence decision that hangs the recommendation pass off this job's completion now has a working
  trigger under it. The two blockers-table rows this bullet points at are struck through accordingly below.
  **Still true, and the reason (a)/(b) are not live yet:** Gaps 318 and 319 are *uncommitted*, so `cb96d8f`
  does not carry them — the recommendation pass and its `ops_recommendation` mirror need a **further** image
  refresh, distinct from the one that just landed, before Gap 320's panel renders a single row.
- `[x]` ~~**(a) The recommendation pass.**~~ **Built 2026-08-25 — Gap 318.**
  **`services/ops_recommendation.py`** (new) + `recommendation_pass_step()` in
  `scripts/run_agent_eval.py`, exactly as scoped: a step appended to the nightly job's own script,
  no new scheduled resource. Its public surface is
  `evaluate_container_health()` / `evaluate_cost()` / `evaluate_ai_improvement()` /
  `collect_container_health()` / `parse_container_metrics()` / `run_recommendation_pass()`, returning
  `RecommendationPass` → `CategoryRecommendation` → `Finding`. Four statuses, not two:
  `worked`, `recommend`, `no_data` (the data could not be read — never a clean bill of health) and
  `insufficient_data` (read, but below the workbooks' n=20 minimum-sample guard; the values are still
  reported, which is the prose form of the `-1 → "n/a — see Detail"` sentinel).

  **Every band is the tile's band.** The sample table below supplied the per-field *judgement*; the
  numbers were read out of this repo's two workbook JSONs' `thresholdsGrid` blocks — `container-status`,
  `container-scale-config`, `container-restarts`, `cost-trend-budget`, `d1`–`d4`, `e1-*`, `b1-error-rate`.
  A test parses both JSONs at test time and fails if a constant ever drifts from the panel it mirrors.
  Cost's two ratios are computed from the same two source fields as `cost-trend-budget`'s KQL
  (`month_to_date_total` / `budget.amount`, and the budget's own `forecastSpend`), so the tile and the
  recommendation cannot report different numbers. Three coloured-but-not-judged exceptions are
  documented in the module: replica count, persona/median latency, and the "CPU persistently <20%" row,
  the last because "persistently" is a multi-day trend and a 1h average cannot support it.

  **Track 1 → Track 2 handoff, the one thing the design under-specified.** The nightly job is
  `run_extraction_benchmark.py … && run_agent_eval.py …` — two *processes*, so Track 1's results were
  never in Track 2's memory. `services/benchmark_artifacts.py` gained `track1_handoff_path()` /
  `write_track1_handoff()` / `read_track1_handoff()` (+ the `BENCHMARK_TRACK1_HANDOFF` override): Track 1
  drops its summary in the temp directory, Track 2 reads it. Written independently of `--no-write`
  (the nightly job is the caller that passes that flag and the caller that needs the handoff), and
  refused when stale (>6h) or from a different cadence, so last night's recall can never be graded as
  tonight's. Missing handoff ⇒ the category says so on `errors` and grades Track 2 alone.

  **Nightly-only, and fail-soft twice over.** `predeploy` is excluded because its 5-case subset is below
  the n=20 guard and because it runs on every push — two live ARM reads in the deploy path is what the
  nightly-completion trigger exists to avoid; `adhoc` is a developer's own run. Each category is
  evaluated in its own try/except (an unauthorized Resource Graph must not delete the AI-quality verdict
  from the same run), and the whole step is wrapped so it cannot turn an otherwise-successful job red —
  the Gap 308/317 failure class this pass was built to watch for.

  `run_recommendation_pass()` itself still persists nothing — it returns and prints, which is what keeps
  computing a verdict separable from storing one. Item (b) below, closed the same day, is what mirrors
  that return value to telemetry.
- `[x]` ~~**(b) Somewhere to persist a run's recommendations.**~~ **Built 2026-08-25 — Gap 319.** A
  custom-event mirror, exactly the pattern `agent_eval_run` / `online_eval_signal` use, because a
  workbook can only read Log Analytics / App Insights / Resource Graph / ARM / ADX — **it cannot query
  Postgres**.

  **Event name: `ops_recommendation`** (`telemetry.OPS_RECOMMENDATION_EVENT_NAME`), emitted by
  `telemetry.track_ops_recommendation()`. **One row per category per run — three rows a night, never one
  row carrying a three-element array.** A workbook grid is a flat row set and item (c)'s columns are
  `Category | Status | Explanation | Recommendation`, i.e. one row per category by construction; the
  nested form would force every panel to `mv-expand` before it could filter or colour on `status`. Same
  reasoning `online_eval_signal` used when it chose one row per signal over one row per window.

  **Fields on the event** (all flat; `customDimensions` / `parse_json(Properties)`):
  `run_label`, `category`, `title`, `status`, `explanation`, `recommendation`, `worst_severity`,
  `finding_count`, `red_count`, `yellow_count`, `findings` (JSON array as a string),
  `findings_omitted`, `error_count`, `errors` (the category's error list joined with ` | `),
  `generated_at`. Four choices worth stating:

  - **`generated_at` is the run key.** Set once by the pass and stamped identically on all three rows, so
    "the latest run" is one `arg_max(generated_at, …)` and can never return two categories from one run
    and one from another. `TimeGenerated` is ingestion time and is deliberately not that key.
  - **The counts ride next to the blob.** `finding_count`/`red_count`/`yellow_count` exist so a panel can
    count reds without `parse_json` + `mv-expand`, and so a trend over a *window* of runs is buildable —
    the same reason `extraction_benchmark_run` carries raw confusion-matrix cells next to its ratios.
  - **`findings` is bounded so that it stays valid JSON.** Application Insights caps a single property
    value at 8,192 characters and would cut a longer one mid-object during ingestion, silently
    de-serialising the array. So the cut is made here instead: at most
    `MAX_RECOMMENDATION_FINDINGS` = 25 entries, each field truncated at 400 chars, whole entries dropped
    from the end until the serialised text fits `MAX_RECOMMENDATION_FINDINGS_CHARS` = 8000, and one
    same-shaped `{"field": "(omitted)", …}` marker entry appended saying how many went. `explanation` /
    `recommendation` / `errors` use the module's existing `_truncate()` marker at 2,000 chars.
  - **`metrics` is not mirrored**, the one deliberate departure from `to_dict()`. It is unbounded by
    design (a dict per container app) and every number in it already has its own event and panel —
    `azure_cost_snapshot` for spend, `agent_eval_summary` for the quality means, live Azure Monitor
    metrics for CPU/memory. The event carries the verdict and the fields that produced it, which is what
    nothing else can say. No `tenant_id`/`request_id` either, matching `agent_eval_summary` /
    `extraction_benchmark_run` / `azure_cost_snapshot`: a scheduled ops pass has no request and no tenant
    in scope, and an always-empty column invites a join that can never match.

  **Wiring**: `services/ops_recommendation.py::mirror_recommendation_pass()` (returns a `MirrorResult`,
  never raises, same contract as `mirror_extraction_run`/`mirror_agent_eval_run`), called from
  `scripts/run_agent_eval.py::recommendation_pass_step()` immediately after the pass prints. Still
  nightly-only — the gate is unchanged and now covers the emission too — and still inside the
  swallow-everything wrapper, so persistence is fail-soft twice over. Skipped under `--no-mirror`, which
  already means "emit no event, upload no artifact" for the `agent_eval_summary` mirror. The step
  re-attaches the exporter (idempotent) and **flushes again**: `main()`'s own mirror block has already
  flushed by the time this runs and the OTel exporter batches on a timer, so without a second flush these
  three events would die with the process — the "the job ran and the workbook shows nothing" symptom the
  mirror exists to prevent.
- `[x]` ~~**(c) A new Workbook panel that renders the persisted recommendations.**~~ **Built and deployed
  2026-08-26 — Gap 320.** One panel, on **both** workbooks — a plain grid of `Category | Status |
  Explanation | Recommendation` (plus `Findings`/`Red`/`Yellow`/`Errors`/`Run`) filtered to the latest run.
  `ops-recommendations-header` + `ops-recommendations` in `cost_health_workbook.json` (25 → 27 items);
  `section-h-header` + `h1-ops-recommendations` in `ai_control_tower_workbook.json` (49 → 51 items,
  Section H). The `query` string is byte-identical across both files (sha256-verified), only the panel
  `title` differs. Source is `AppEvents | where Name == "ops_recommendation"` on the raw
  `law-invoicellm-dev` workspace (not the App-Insights-classic `customEvents` alias), the per-run filter is
  a `toscalar(... | summarize max(run_ts))` global max over the `generated_at` property (not `arg_max(...)
  by category`, which can blend two runs' categories if a run ever emits fewer than 3 rows), and
  `Recommendation` renders the event's own text when non-empty, else the literal `"No recommendation
  yet"` — never inferred from data volume. **No colouring** (plain grid, no `visualization`/`tileSettings`/
  `customWidth`/`conditionalVisibility`), deliberately: a row can carry a "bad" `worst_severity` while
  `recommendation` is empty, and colouring that would visually contradict "No recommendation yet". Found a
  new KQL trap doing this: `title` is a reserved word, `d.title` fails to parse — fixed with bracket
  notation `d["title"]` (added to the traps list above). Verified live: compiles (both JSONs valid, both
  bicep files build clean), schema-valid (0 errors against Microsoft's `schema/workbook.json`), the query
  runs live against `law-invoicellm-dev` (0 rows, as expected today), a synthetic 4-row `datatable` proved
  the "No recommendation yet" branch, both bicep `what-if`s showed `Modify` not `Create`, both
  `az deployment group create` runs succeeded, and the pulled-back live `serializedData` deep-compares
  27/27 and 51/51 items identical to the local files. Full evidence in `be_features_tracker.md`'s Gap 320
  entry.

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

Verified as of 2026-08-24, still open (last row added 2026-08-25 under Gap 317).

**Correction 2026-08-26 (doc-reconciliation pass, live-Azure-verified architect audit):** three of these rows
were stale — the alert-rule row, and the two "pending image refresh" rows. Each is struck through in place
with the live evidence in its own Detail cell; the original wording is kept underneath it, not replaced
(CONVENTIONS hard rule 4). **Four rows remain genuinely open** and are untouched: `Monitoring Reader` RBAC,
SendGrid, the `-critical` action-group split, and Stage 8 (`08-apps.bicep`, tracker Gap 298). The CI
`benchmark-gate` row was already correctly struck through. Net: this table is now 4 struck-through / 4 open,
not "all still open". One thing the image refresh did **not** carry, so it is not marked resolved anywhere
below: `ops_recommendation` is still 0 rows, because Gaps 318/319 are uncommitted and no image contains them.
**Superseded 2026-08-26 (redesign session, later the same day):** that sentence is no longer true — Gaps 318/319/320 are
committed (`f9aa0c5`) and deployed and the nightly run has produced real `ops_recommendation` rows. Kept above rather than
rewritten, per hard rule 4. See Fix 9 in "Workbook redesign — priority-ranked information architecture (2026-08-26)".

**Correction 2026-08-26 (Monitoring Reader / Cost Management Reader RBAC, deployed; SendGrid wired):** the `Monitoring
Reader` row below is now also struck through — it and Gap 297's `Cost Management Reader` were both granted
the same day via `infra/rbac-monitoring-cost-only.bicep`, not a Stage 7 redeploy (see `be_features_tracker.md`
Gap 297's closure note for the full 4-rung verification). SendGrid was also wired and verified live the same day (Gap 321).
**Two rows remain genuinely open**: the `-critical` action-group split, and Stage 8.

| Blocker | Detail |
|---|---|
| ~~CI `benchmark-gate` step is broken~~ — **removed, not fixed** | The `-c` argument bug (`az containerapp job start --command /bin/sh -c` → `unrecognized arguments: -c`) is moot: 2026-08-25, the entire `benchmark-gate` job was deleted from `deploy-dev.yml` per a standing instruction that the CI/CD deploy pipeline must never execute tests or benchmarks, not even indirectly via an Azure-side job execution. `deploy-backend`/`deploy-worker` now depend only on `changes`. No CLI fix needed or wanted — see Gap 312 in `be_features_tracker.md`. The direct-ARM `az rest` workaround noted in the prior version of this row was never applied and should not be revived for this purpose. |
| ~~`Monitoring Reader` RBAC not granted~~ — **granted 2026-08-26** | **Correction 2026-08-26 (live-Azure-verified):** deployed via the narrow standalone `infra/rbac-monitoring-cost-only.bicep` (not a Stage 7 redeploy — Stage 7's naming drift is unchanged, see the Stage 8 row below for the same class of problem on Stage 7's storage-account name). `az role assignment list --assignee b9e91856-... --all` now returns **7** roles including `Monitoring Reader` at `rg-invoice-llm-dev` scope. Closure test actually run as the managed identity via `az containerapp exec` into `ca-invoice-be-dev`: a live Resource Graph query for `microsoft.app/containerapps` and a `Microsoft.Insights/metrics` read both succeeded with no 403, using `services/azure_cost.py`'s `arm_request()` (the same function `ops_recommendation.py::collect_container_health()` calls). `ops_recommendation.py` is not yet in the deployed image, so Gap 318's `container_health` category still needs its own next-nightly-run confirmation — this closes the RBAC blocker only. Original (now superseded) wording, kept for history: Declared in `infra/modules/security/rbac-assignments.bicep`, never deployed. `id-invoicellm-dev` holds 5 roles, not this one (verified live). Without it, anything reading `alertsmanagementresources` returns zero alerts. A plain Stage 7 (`07-rbac.bicep`) redeploy fails first on the naming drift — its default prefix resolves to `stinvoicellmdev`, live is `stinvoicellmdev2`. Needs a `namingPrefix` override or a narrow-scoped standalone template. |
| ~~SendGrid not wired~~ — **wired and live-verified 2026-08-26** | **Correction 2026-08-26 (live-Azure-verified):** `SENDGRID-API-KEY` and `SENDGRID-INBOUND-SECRET` seeded in Key Vault `kv-invoicellm-dev`, secret references `sendgrid-key-secret` and `sendgrid-inbound-secret` wired into `ca-invoice-be-dev`, and all email/domain/admin env vars configured (`SENDGRID_SENDING_DOMAIN`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME`, `EMAIL_APP_DOMAIN`, `EMAIL_APP_ADDRESS`, `SUPPORT_NOTIFY_EMAIL`, `ALLOW_MOCK_AUTH=false`, `ENVIRONMENT=production`). Revision `ca-invoice-be-dev--0000089` running cleanly (`ProvisioningState: Succeeded`). `infra/modules/compute/invoice-be.bicep` and `infra/params.dev.json` synced and compiling clean (`az bicep build` 0 errors). Original (now superseded) wording, kept for history: `ca-invoice-be-dev` lists 11 secrets and `sendgrid-key-secret` is **not** among them, though `invoice-be.bicep` declares it. Any email path raises `SENDGRID_API_KEY is not configured` until a deploy seeds it. |
| No Teams receiver on a `-critical` action group | `action-group.bicep` declares a `-critical` / `-info` split (Teams/Slack webhooks on `-critical` only, `-info` deliberately `webhookReceivers: []`). **That split is not deployed** — `ag-invoice-llm-dev-critical` 404s live. What exists is `ag-invoice-llm-dev` and `ag-invoicellm-dev`, both notifying the identical destinations: one email receiver (`application@infinevocloud.com`) and one webhook receiver `teams-alert-channel` pointing at a Power Automate flow with `useCommonAlertSchema: true`. Any future delivery/target decision must account for this — including that a Sev-based critical/info destination split does **not** exist today. |
| ~~Correction 2026-08-26 (found while verifying an action group name for Gap 299, not a Gap 299 deliverable)~~ — **the "404s live" half of the row above is stale; the "no Teams receiver" half still holds.** `az monitor action-group list -g rg-invoice-llm-dev` and `az monitor action-group show` (run to confirm which group Gap 299's new alert should target) found `ag-invoice-llm-dev-critical` **and** `ag-invoice-llm-dev-info` now exist live — they do not 404. `ag-invoice-llm-dev-critical` has one email receiver (`sbanerji@admsofttech.com`, a different address than the shared groups above) and **zero webhook receivers**, so the row's substantive finding (no Teams/Slack delivery on a critical-labelled group) is still true even though its "not deployed" framing is not. Who/when deployed these two groups, and whether anything should route to them, is unreconciled and explicitly not investigated further here — out of scope for Gap 299, which targets `ag-invoice-llm-dev` only (see `be_features_tracker.md` Gap 299's closure note). |
| Stage 8 (`08-apps.bicep`) is unrunnable against dev | `params.dev.json`'s `backendImage` points at `acrinvoicellmdev.azurecr.io` — **that registry does not exist**, the real one is `acrinvoicellmdev2` — and its `namingPrefix: "invoice-llm"` rewrites every Key Vault secret URI and the identity to names that do not exist. A Stage 8 deploy would also roll back the live CPU/memory scale rules. Anything new must deploy through a narrow standalone template, the pattern `workbook-cost-health-only.bicep` / `workbook-ai-control-tower-only.bicep` / `benchmark-eval-job-only.bicep` already use. |
| ~~Alert-rule fix pending deploy~~ — **deployed and live, verified 2026-08-26** | **Correction 2026-08-26 (live-Azure-verified):** this row was stale and contradicted its own Gap entry. `be_features_tracker.md`'s **Gap 301** records the change as "fixed, deployed and verified live the same day," and **the tracker is the one that is right**: `alert-ca-invoice-be-dev-cpu-high` exists live carrying **both** criteria — `CpuPercentage` Avg > 90 **AND** `Replicas` Max >= 5 — read back with `az`, not inferred from the template. So the second `AllOf` criterion is in Azure, the alert only fires once autoscale is genuinely maxed out, and nothing is pending. Original (now superseded) wording, kept for history: `alert-rules.bicep`'s CPU/memory alerts gained a second `AllOf` criterion (`Replicas >= app.maxReplicas`) so they only fire once autoscale is genuinely maxed out. `az bicep build` clean, `what-if` Succeeded — **`az deployment group create` deliberately not run.** |
| ~~`chat_turn` / GenAI-span / `AppRequests` fixes pending deploy~~ — **resolved and live as of the 2026-08-25 image, verified 2026-08-26** | **Correction 2026-08-26 (live-Azure-verified):** the deploy this row was waiting for **has happened**. The backend image was rebuilt **2026-08-25T14:41Z from commit `cb96d8f`**, which carries all three fixes. Confirmed live in `law-invoicellm-dev`, by query rather than by reasoning about the commit: `AppEvents` now has real `chat_turn` rows (so Sections B and C are no longer structurally empty), `AppDependencies` now has `GenAI \| az.ai.openai` rows (so the LLM-call dependency span is exporting), and `AppRequests` now has rows **from the real container** — not just the `invoice-be-local-f20-verify`-tagged rows Gap 292 produced from a local run. The "real data today vs. structurally empty" table above is corrected to match. **What this image does *not* carry**, and therefore what this row must not be read as closing: Gaps 318/319 are uncommitted, so `ops_recommendation` is still 0 rows and Gap 320's panel still renders empty — a *further* image refresh, not this one. Original (now superseded) wording, kept for history: All three are code-complete and locally verified but the live backend image predates them, so Sections B/C stay at 0 rows and `AppDependencies` has no `GenAI \| az.ai.openai` rows until a backend deploy lands (no longer blocked by `benchmark-gate` — that gate is removed as of 2026-08-25, see the row above). |
| ~~Nightly eval job's `FileNotFoundError` fix pending the *same* deploy~~ — **resolved and live; the job succeeded 2026-08-26T03:00** | **Correction 2026-08-26 (live-Azure-verified):** same resolution as the row above — the 2026-08-25T14:41Z image built from commit `cb96d8f` carries Gap 308's `default_output_dir()` and Gap 317's caller-side half. The proof is not "the fix is in the image" but the run itself: **`caj-benchmark-eval-dev`'s 2026-08-26T03:00 UTC execution succeeded**, i.e. the schedule that had been failing every night under `retryLimit 0` after doing all its real work now completes. That also means the nightly trigger the recommendation pass hangs off (Gap 318's cadence decision) is real in Azure and not just in code. Original (now superseded) wording, kept for history: Code-complete (Gap 308's `default_output_dir()`, 2026-08-24; re-verified and extended by Gap 317, 2026-08-25) and proven inside a real `Dockerfile.be` build — the literal nightly argv now exits 0 and writes `/tmp/agent_eval_output.json`. But `acrinvoicellmdev2.azurecr.io/invoice-be:latest` was built **2026-08-24T09:08:22Z**, ~4h before the fix commit, and reading `/app/scripts/run_agent_eval.py` inside it shows **no `default_output_dir` at all** — so `caj-benchmark-eval-dev` still fails at 03:00 UTC every night (all real work done, then the crash, recorded `Failed` under `retryLimit 0`) until an image refresh lands. Same deploy as the row above; nothing else is needed. |

---

## Workbook redesign — priority-ranked information architecture (2026-08-26)

**Status: design approved by the founder, not implemented.** Decided directly with the founder across an
extended design session on 2026-08-26. This section is **additive** (CONVENTIONS hard rule 4) — nothing
above it is rewritten or withdrawn. Everything above remains the record of *what is deployed today*: the
27-item / 51-item panel inventories, the sample field-recommendation table, the KQL traps list, the ARG
quirks and the blockers table are all still true and still load-bearing. This section is the **target
shape**, plus the audit evidence that produced it.

**Update 2026-08-26 (infra-devops, Gap 322) — implemented and deployed live to `rg-invoice-llm-dev`.**
Both workbooks restructured onto the 3-tier layout below; all 11 fixes applied; the new Dashboard Insights
latency panel added; recommendation cards moved inline. Panel-inventory counts above (27/51) are now
**stale for the live workbooks** — the current live counts are `cost_health_workbook.json` **30 items**,
`ai_control_tower_workbook.json` **55 items** — kept as written above per hard rule 4 (they were true at
the time), corrected here rather than edited in place. Full verification (bicep build, what-if, deploy,
pull-back byte-comparison, live query proof against real Log Analytics, backend test XPASS confirmation)
is in `be_features_tracker.md`'s Gap 322 entry. The fix list and tier structure below are marked
`[x] implemented` inline, per-item, rather than rewritten.

**Ownership boundary.** This section is written by senior-dev as a spec; the implementation is
infra-devops's — the two workbook JSONs (`infra/monitoring/cost_health_workbook.json`,
`infra/monitoring/ai_control_tower_workbook.json`) and their two narrow bicep templates
(`infra/workbook-cost-health-only.bicep`, `infra/workbook-ai-control-tower-only.bicep`). No production
code change is in scope here; the one place where a workbook change *forces* a code change is called out
explicitly under "Fix 11" below, and it needs its own gap number rather than being folded in.

### The organizing principle — the founder's priority order

Three tiers, in this order, in the founder's own words:

1. **Cost & Reliability** — top priority. *"Be aware of running cost, reduce cost, improve UX quality —
   system running fast, nothing breaking."*
2. **Extraction & Chat Quality** — second priority. Both are already good; this tier exists to catch
   **regressions** and to keep improving them, not to prove they work.
3. **Cost Reduction** — explicitly **last / lowest** priority.

The inversion is the point. Cost *reduction* — where spend concentrates, by service, by component — is
the most built-out area of the current Cost + Health workbook (it is the first thing on the page,
`cost-header` → `cost-trend-budget` → `cost-by-service`), and it is the founder's lowest priority.
Today's layout orders panels by how much was built, not by what has to be looked at first. The redesign
reorders on priority.

### The 3-tier structure — both workbooks share it

Both workbooks adopt the same three tiers in the same order. They differ only in which fields each has
data for; a tier with no fields on a given workbook is simply absent there rather than rendered empty.

| Tier | Sub-section | Fields in the sub-section | Where the data is today |
|---|---|---|---|
| **1 — Cost & Reliability** | Cost awareness | MTD spend vs. budget; month-end forecast vs. budget | `cost-trend-budget` (Cost+Health) — see Fix 1, it is reading a stale snapshot |
| | Reliability | Container CPU / memory; restarts (24h); database health; cache health; failed message queue (DLQ) | `container-status`, `container-restarts`, `db-status-postgres*`, `db-status-redis*`, `dlq-panel` — see Fixes 2 and 3 |
| | Speed | Major API latency by feature area **vs. industry standard**; API error rate by area | `api-perf-by-area`, `api-perf-error-rate` — the "vs. industry standard" comparison is new, see the latency table below |
| **2 — Extraction & Chat Quality** | Extraction quality | Alert recall; clean-doc false-positive rate; field accuracy trend | `e1-alert-recall`, `e1-fp-rate`, `e3-trend` (AI Tower) |
| | Chat quality — nightly test | Pass rate; **all six** soft scores (faithfulness, relevance, accuracy, context, orchestration, persona); cost per turn; response time (P95) | `d1`–`d4` (AI Tower) — see Fix 11, `d1`/`d2-accuracy` bands are miscalibrated |
| | Chat quality — real usage | Production judge scores, once real traffic exists | `g1`/`g2` (AI Tower) — 0 rows today, see the "real data vs. structurally empty" table above |
| **3 — Cost Reduction** | Where cost concentrates | Spend by Azure service; spend by component (chat vs. extraction vs. judging); test vs. real spend | `cost-by-service` (Cost+Health); `a1`/`a2` (AI Tower) — the chat/extraction/judging split is **new**, see the extraction-cost finding below |

**Tier 1's "Speed" sub-section is the one place a comparison, not just a number, is required.** A P95 in
milliseconds means nothing to a reader who does not already know what good looks like for that feature
area. Each Speed row carries its industry-standard reference in `Detail` (see the latency table below for
the reference values), so a reader can tell "10.5s" apart from "10.5s, which is normal for this".

### Recommendation cards move inline — this is a requirement, not a preference

Gap 320 put the recommendation grid at the **bottom** of both workbooks (`ops-recommendations-header` +
`ops-recommendations` as items 24/25 of 27; `section-h-header` + `h1-ops-recommendations` as items 48/49
of 51). The founder was explicit that burying the recommendations at the end is a **real usability
problem**: the reader sees the number at the top of the page and the explanation of that number several
screens below it, so in practice the explanation is never read.

**Required shape:** the recommendation cards render **inline within each tier, next to the data they
explain**, not as one separate section at the bottom. There is no separate recommendations section any
more; the bottom-of-page grid is removed once its content is distributed.

The `ops_recommendation` event already supports this without any emitter change — it carries `category`,
one row per category per run (Gap 319), and the three categories map cleanly onto the tiers:

| `ops_recommendation.category` | Renders inside |
|---|---|
| `container_health` | Tier 1 → Reliability |
| `cost` | Tier 1 → Cost awareness (the *awareness* verdict), and Tier 3 → Where cost concentrates (the *reduction* verdict), if the founder wants it in both |
| `ai_improvement` | Tier 2 (spans both the extraction and chat sub-sections) |

**Two implementation constraints on the split**, both inherited from Gap 320's verification and neither
optional:

- **The "latest run" scalar must still be a global max computed before the category filter.** Gap 320's
  query computes `let latest_run = toscalar(rows | summarize max(run_ts));` over *all* rows and only then
  filters. If a per-tier panel narrows to one category first and *then* takes the max, two tiers can
  render two different runs' verdicts side by side on the same page. Keep the `toscalar` global max, add
  the `| where tostring(d.category) == "<category>"` predicate **after** it.
- **`title` is still a reserved word** — the `Category` column must stay `tostring(d["title"])` in bracket
  notation in every copy of the query. See the traps list above.

The rest of Gap 320's query contract carries over unchanged to each inline copy: run key is
`generated_at` and never `TimeGenerated`; `Recommendation` renders the literal `"No recommendation yet"`
when `d.recommendation` is empty and is never inferred from data volume; plain grid, no colouring (a row
can carry a bad `worst_severity` while `recommendation` is empty, and colouring that would visually
contradict "No recommendation yet").

### Field-level findings from the 2026-08-26 audit — the rationale for the above

**1. Extraction genuinely has its own real cost, and it is invisible today.** Tonight's run:
**$0.145 of $0.25 total — 58%**, i.e. more than chat and judging combined. Nothing on either workbook
shows this. `a1-cost-by-agent` splits by `agent_name` and `a2-spend-by-run-source` splits by
`run_source`, but neither answers "how much of the bill is extraction vs. chat vs. judging?" — which is
the question Tier 3's "spend by component" row exists to answer, and the reason that row is specified as
new rather than as a re-label of `a1`.

**2. `d1-latest-pass-rate` and `d2-accuracy` are coloured against current mediocre performance, not
against what "good" means.** Read live out of `ai_control_tower_workbook.json`:

| Panel | Current `thresholdsGrid` | Tonight's real value | Renders as |
|---|---|---|---|
| `d1-latest-pass-rate` | red `< 0.20`, yellow `< 0.30`, default green | **25.7%** | yellow-at-best, and green under the `-1` sentinel path |
| `d2-accuracy` | red `< 0.40`, yellow `< 0.55`, default green | **60%** | **green** |

A 25.7% pass rate and 60% accuracy are not green. The bands were set to whatever the system was doing at
the time, so the tile can no longer report a bad number as bad — which is the entire job of a coloured
tile. Recalibration is infra-devops's, with the code coupling in Fix 11.

**Update 2026-08-26 — the code half of this is done (Gap 323).** `SCORE_BANDS["pass_rate"]` is now
`(0.60, 0.75)` and `SCORE_BANDS["accuracy"]` is now `(0.75, 0.90)`, so both of tonight's real numbers
grade **red** in the recommendation pass. The two tiles still carry the old grids; the exact values to
mirror, the reasoning behind them, and the three handover notes are in **Fix 11** below.

**3. The n=3-run guard on the golden bank is wrong on its own terms.** Both `d1` and `d2-accuracy` carry
`iff(total < 3, -1.0, …)` — the `-1 → "n/a — see Detail"` sentinel — waiting for three runs before they
will colour. But the golden bank is a **fixed, deterministic, exhaustive 35-case script set run
identically every night**. There is no sampling error for a "wait for more runs" guard to protect
against; a second and third identical run add no statistical information, they only delay the colouring.

This is not a new argument — it is the **same argument this repo already accepted one level down**.
`services/ops_recommendation.py` exempts `context_drift` from its own n=20 guard in a comment that reads,
verbatim:

> the guard exists because a *rate* over a small sample is noise; this is a fixed, exhaustive,
> deterministic script set — the same handful of pinned checks every night, with no sampling error to
> guard against.

The redesign applies that identical reasoning one level up, to Section D's own bands. Note this is
narrower than "remove all minimum-sample guards": the **n=20 turn/call guard on live-traffic rates stays**
— those *are* rates over a variable sample and the guard is correct there. Only the n=3-**run** guard on
the deterministic golden bank is wrong.

**4. Real API latency vs. industry standard.** Live-queried over the last 7 days, per feature area. These
are the reference values Tier 1's Speed sub-section renders in `Detail`:

| Feature area | Measured (last 7d) | Industry standard | Read |
|---|---|---|---|
| Auth | P50 268 ms / P95 544 ms | sub-second | **Good** |
| Ingestion & Extraction | P50 353 ms / P95 705 ms | sub-second | **Good** |
| Chat | P50 10.5 s / P95 28.6 s | 2–10 s for agentic RAG | **Normal for an LLM-backed response**, though P95 is on the high side and worth watching |
| Dashboard & Reporting (Insights) | P95 23.1 s | — | **Root-caused, not noise** — see finding 5 |
| Review & Correction | **zero traffic in 7 days** | — | Unknown — worth checking whether that is real (nobody used it) or an instrumentation gap |
| Billing & Admin | **zero traffic in 7 days** | — | Same |

The two zero-traffic areas are recorded as a **question, not a defect**. `api-perf-by-area`'s `case()`
maps `/audit` → "Review & Correction" and `/billing` or `/admin` → "Billing & Admin"; whether those
prefixes still match the live routers was not checked in this pass and should not be assumed either way.

**5. Dashboard Insights' latency is a real finding that is already root-caused in the code itself.**
`routers/dashboard.py::get_dashboard_insights` — its own docstring (Gap 30, Gap 279) says it: the handler
calls Azure OpenAI **synchronously** to generate the dashboard's AI recommendations, **measured live at
13–19.5 s on a cache miss** and sub-second on a hit (`INSIGHTS_CACHE_TTL_SECONDS = 3600`). Tonight's live
data confirms the bimodality directly: of 6 real calls, **4 took 13–23 s and 2 were under 1 second**.

A worse version of this bug was already fixed. Under **Gap 279** the handler was declared `async def`
while its body was entirely blocking I/O, so Starlette ran it on the uvicorn event loop and that 13–19 s
call **froze the whole worker** — the docstring cites `2026-08-19T07:20:30Z`, where `/dashboard/insights`
(16781 ms) and four unrelated concurrent requests (16750/16945/16956/16937 ms) all completed within
200 ms of each other and `/invoices` went straight back to 282 ms one second later. That is fixed (the
handler is deliberately `def`, not `async def`, and the docstring says so in capitals). **The remaining
latency is the inherent cost of a live LLM call on a cache miss** and affects only the caller.

**What the redesign does about it: adds observability, nothing else.** A panel that shows the cache-miss
vs. cache-hit split for `/dashboard/insights` so the bimodality is visible rather than being averaged
into one meaningless P95. **Actually fixing the latency — pre-warming the cache, or moving generation to
a background job — is explicitly OUT of scope** and is a separate future gap.

### The fix list — panel-level defects found in the 2026-08-26 audit

This is infra-devops's fix list and is meant to be implementable from this document alone. Every "current
state" line below was read out of the committed workbook JSON during this pass, not paraphrased from
memory. **senior-dev did not fix any of these** — they are workbook JSON, which is infra scope.

**1. `cost-trend-budget` / `cost-by-service` (Cost + Health) — reading a stale cost snapshot.**
Current state: both read `AppEvents | where Name == "azure_cost_snapshot"` / `"azure_cost_slice"`, and
the newest snapshot in the workspace predates the budget fix — it carries the old **₹150** budget, not
the **₹20,000** that is actually deployed (`budget-invoicellm-dev`, confirmed live 2026-08-26, see the
"verified facts" list above). Root cause is that `scripts/sweep_azure_cost.py` **was never scheduled**,
so no fresh snapshot has ever been written. Required change: show the live-corrected number if that is
achievable from the workbook alone, **or** clearly flag the panel as stale (e.g. surface the snapshot's
own age in `Detail`) if it is not. **Scheduling the sweep is OUT of scope here** — that is a separate
infra job-creation task. What is not acceptable is the current state, where a stale number renders as if
it were live.

**Implemented (Gap 322, 2026-08-26):** converted from `top 1 by TimeGenerated desc` to the
`toscalar`/equality pattern (folding in the same-shaped `top 1` trap noted at the end of Fix 8 below);
stale-snapshot age (`snapshot_age_hours`) now surfaced in `Detail`. Deployed and pull-back-verified live;
live query today returns `budget_amount=150` (the known-stale ₹150 figure) and `snapshot_age_hours=74.1`.

**2. `db-status-redis-liveness` (Cost + Health) — permanent false red.**
Current state: `AzureMetrics | … | where MetricName == "geoReplicationHealthy" | summarize Value =
avg(Average) | extend Status = iff(Value >= 1, "Healthy", "Unhealthy")`, coloured green on `== "Healthy"`
and **red by default**. Dev's Redis has **no geo-replication configured**, so the metric never arrives,
`avg()` over the empty set is null, `null >= 1` is false, and the panel falls through to a permanent
false `"Unhealthy"` red. Required change: render **"N/A — not configured in this tier"** (blue, the same
role the `-1` sentinel plays elsewhere) when the metric is absent, and reserve red for a real
`geoReplicationHealthy == 0`. Absence of a metric and a failing metric are different facts.

**Implemented (Gap 322, 2026-08-26):** absent metric now renders `"N/A — not configured in this tier"`
(blue) instead of a false red `"Unhealthy"`; a real `geoReplicationHealthy == 0` still renders red. Deployed
and live; live query today actually returns `Healthy` (the metric is currently present, not absent) — the
null-guard path is verified structurally, not exercised by today's data.

**3. `db-status-postgres-liveness` (Cost + Health) — a 6-hour average of a liveness signal.**
Current state: `where TimeGenerated > ago(6h) | where MetricName == "is_db_alive" | summarize Value =
avg(Average) | extend Status = iff(Value >= 1, "Alive", "Down")`. Because it averages over 6h and demands
`>= 1`, a **single blip** drags the average below 1 and the tile reads `"Down"` — and keeps reading
`"Down"` for six hours *after* the database has recovered. Required change: read a shorter / real-time
window (latest sample, or a few minutes) so the tile reports current liveness. If a historical blip is
worth surfacing at all, it belongs in `Detail` as "N blips in 6h", not in the headline status.

**Implemented (Gap 322, 2026-08-26):** converted to a real-time read — latest sample in the last 15 min —
with a 6h blip count carried in `Detail`. Deployed and live; live query today returns `Alive`, `0 sub-1
samples in last 6h`.

**4. `alerts-trend` (Cost + Health) — titled "per day", has no daily binning.**
Current state: title is `"Alerts fired per day, by severity — last 14 days"`, query is
`… | where fired > ago(14d) | summarize Value = count() by Metric = sev`. There is **no `bin()` and no
division by 14** anywhere — it is a 14-day **cumulative** count presented as a daily rate, so every
number on the tile is ~14× what the title claims, and the red band at `>= 5` fires on a 14-day total of
5. Required change: either bin by day (`by bin(fired, 1d), sev`) or retitle to "last 14 days, total" and
re-band accordingly. Whichever is chosen, the title and the arithmetic must agree.

**Implemented (Gap 322, 2026-08-26):** converted to real `bin(fired, 1d)` daily binning (Resource Graph
`bin()`, rendered as a plain grid rather than tiles, matching the multi-row-per-metric shape). Deployed and
live; `az graph query` today returns 11 distinct day/severity rows across the last 14 days, not one 14-day
cumulative count.

**5. `a5-genai-dependency-duration` (AI Tower) — never filters `run_source`.**
Current state: `AppDependencies | where DependencyType startswith "GenAI" | … | summarize … by
agent_name`. There is no `run_source` predicate anywhere in it. This panel exists as a **production
cross-check against `a3-latency-by-agent`**, but it silently blends golden-bank/eval traffic and
production traffic into one number, so the cross-check compares a mixed population against a filtered
one. Required change: add the same `run_source` filter the rest of the workbook uses —
`extend run_source = iff(isempty(run_source), "production", run_source) | where run_source ==
"production"` — matching the pattern already in `b6-stop-reasons`. See the "`run_source` filtering" rule
in the "Rules the workbooks already enforce" list above: this panel is the one that violates it.

**Implemented (Gap 322, 2026-08-26):** `run_source == "production"` filter added, matching the
`b6-stop-reasons` pattern exactly. Deployed and live; live query returns 6 production-only agents including
`dashboard.insights` (p50/p95 ≈ 17.7s), confirming both the fix and finding 5's Dashboard Insights
root-cause in the same data.

**6. `a6-sage-per-tool-cost` (AI Tower) — delete this panel.**
Current state: `… | where agent_name startswith "sage."` with `Detail` hard-coding `"structurally empty
while ENABLE_AGENTIC_SAGE=false"`. SAGE was **deleted in Gap 316**; no code emits an `agent_name`
beginning `sage.` any more, so the predicate can **structurally never match again** — this is not a
dormant panel waiting for a flag, it is dead. Required change: **delete the panel** (Section A drops from
`a1`–`a6` to `a1`–`a5`; item count 51 → 50).

**Implemented (Gap 322, 2026-08-26):** panel deleted outright. `section-a-header` updated additively to
drop the stale SAGE reference and note the deletion. Deployed and pull-back-verified live (`a6-sage-per-tool-cost`
does not appear in the live workbook).

**7. `b6-stop-reasons` (AI Tower) — the label is actively wrong, not merely stale.**
Current state: title is `"Stop reasons — SAGE-only field, structurally empty while
ENABLE_AGENTIC_SAGE=false"` and every row's `Detail` hard-codes the same sentence. Both halves are false:
`ENABLE_AGENTIC_SAGE` **no longer exists** (deleted in Gap 316), and `stop_reason` **is populated on the
live default route** — `agents/query_agent.py` writes `sql_attempts_exhausted`, `sql_declined`,
`sql_summary_failed`, `rag_answer_failed`, `chat_answer_failed`, `route_override_followup`, plus
`agent_raised` from `routers/chat.py` and `queue_handler_raised` from `queue_worker/handlers.py`. Since
`chat_turn` started carrying real production rows (the 2026-08-25T14:41Z image), this panel shows **real
data while telling the reader it is empty**. Required change: retitle to describe what it actually is
("Stop reasons — default chat route, 30d") and replace the hard-coded `Detail` with something derived
from the row (e.g. share of turns). Note this panel already filters `run_source == "production"`
correctly — that part is right and should not be disturbed. Contrast with Fix 6: `a6` is genuinely dead,
`b6` is genuinely live; they are not the same problem despite carrying the same stale sentence.

**Implemented (Gap 322, 2026-08-26):** retitled to "Stop reasons — default chat route, 30d, production only";
hardcoded `Detail` replaced with a real derived share-of-turns string. Deployed and live; live query executes
cleanly and today's real data shows 0 of 32 production `chat_turn` rows (last 30d) have a populated
`stop_reason` — an honest empty result, not the mislabeling this fix targeted (which was a false claim, not
a broken query).

**8. `e2-confusion-cells` (AI Tower) — the `top 1` trap the spec claims was fixed everywhere.**
Current state: `AppEvents | where Name == "extraction_benchmark_run" | … | top 1 by TimeGenerated desc |
project …`. The traps list above states plainly that "a bare `top 1 by … desc` returns **zero** rows over
empty input, so 'latest run' tiles use a `summarize`-based `arg_max` tuple, which emits exactly one
(null-valued) row" — and this panel never got converted. Over empty input it renders **nothing at all**
rather than an honest "n/a", which reads as "no problems" instead of "no data". Required change: convert
to the `summarize (…) = arg_max(TimeGenerated, …)` tuple form, matching `d1-latest-pass-rate`.

*Also found in this pass, and offered as a founder call rather than assumed into the fix:*
`cost-trend-budget` (Fix 1) **has the same `top 1 by TimeGenerated desc` trap**. Fixing it is the same
one-line conversion and is arguably part of Fix 1 anyway, but it was not in the founder's stated list, so
it is recorded here rather than silently bundled.

**Implemented (Gap 322, 2026-08-26):** `e2-confusion-cells` converted to the `toscalar`/equality pattern.
`cost-trend-budget`'s same-shaped trap (noted above) was also converted, per the founder's confirmation
that it should be included. Both deployed and live; `e2-confusion-cells`' live query returns real
confusion-matrix counts (`true_positive=5`, `false_negative=0`, `false_positive=1`, `true_negative=3`,
`not_applicable=8`).

**9. `h1-ops-recommendations` (AI Tower) / `ops-recommendations` (Cost + Health) — RESOLVED, record as
fixed.** These rendered 0 rows because Gaps 318 and 319 were uncommitted and therefore in no image. **That
is no longer true as of 2026-08-26**: both are committed (`f9aa0c5`) and deployed, and tonight's nightly
run produced **real rows**. This supersedes the "0 rows / needs a further image refresh" wording in the
"real data today vs. structurally empty" table, the blockers table, and the last unchecked item in the
Tasks list below — all three are updated in place. **Do not carry this forward as an open item.** The only
change these two panels need from the redesign is relocation, per "Recommendation cards move inline".

**Confirmed (Gap 322, 2026-08-26):** relocated inline exactly as predicted — no query change was needed.
`cost_health_workbook.json` carries `tier1-cost-recommendation` / `tier1-container-health-recommendation`;
`ai_control_tower_workbook.json` carries `tier2-ai-improvement-recommendation` only (the `container_health`/
`cost` categories are not duplicated onto AI Tower, which has no underlying panels for them to sit next to
— a design decision made during implementation, see the tracker's Gap 322 entry). All three deployed and
live; live queries return real `no_data` (`container_health`/`cost`) and a real `recommend` row with live
explanatory text (`ai_improvement`).

**10. `f1-breached-signals` (AI Tower) — colours off `breached` alone and never reads `value`.**
Current state: `summarize (latest_ts, latest_breached) = arg_max(TimeGenerated, breached) by signal_name |
extend Status = iff(latest_breached == "1", "breached", "ok")`. `value` is not projected and not read
anywhere in the query. A signal whose denominator is permanently 0 — exactly `budget_exhaustion_rate`'s
state since Gap 316 — therefore renders a **false green `"ok"` forever**. This is the precise failure mode
`services/online_eval_signals.py::SignalResult`'s docstring exists to prevent ("'Nothing happened' and
'nothing went wrong' are different facts"); the emitter honours the contract by sending `value=None`, and
the tile reads the wrong field. Required change: **read `value` as well as `breached`** and render a null
`value` as a distinct "not measured" state (blue), not as green. **This half is fixable independently and
should be done now.** What is *not* unblocked: whether the dead `budget_exhaustion_rate` signal is retired
altogether is **the founder's still-open Gap 305 decision** — leave that alone. Fixing the colouring bug
does not pre-empt it, and is correct regardless of which way Gap 305 goes.

**Implemented (Gap 322, 2026-08-26):** now reads `value` as well as `breached`; a null `value` renders
`"not measured"` (blue) rather than a false green `"ok"`. Gap 305's dead-signal decision left untouched, as
required. Deployed and live; live query executes cleanly (`online_eval_signal` has 0 rows total today — the
emitter is not yet scheduled, a known, unrelated, documented gap — so the fix's logic is verified
structurally rather than exercised against a real breached/null case today).

**11. `d1-latest-pass-rate` / `d2-accuracy` band recalibration — has a code coupling, needs its own gap.**
The recalibration itself (finding 2 above) is a workbook-JSON change. But `d1`'s grid is **pinned by an
automated test**: `tests/test_ops_recommendation.py::test_each_band_is_still_the_live_panels_band` parses
`ai_control_tower_workbook.json` at test time and asserts `d1-latest-pass-rate`'s red/yellow thresholds
equal `services/ops_recommendation.py::SCORE_BANDS["pass_rate"]` (currently `(0.20, 0.30)`). **Changing
the JSON alone turns the backend suite red.** The constant must move with it — which is a production-code
change and therefore needs its own tracker Gap entry (repo rule: no code change without a matching Gap).

`d2-accuracy` is a trap of the opposite kind: it is **not** in that test's parametrize list (only
`d2-faithfulness` is), yet `SCORE_BANDS["accuracy"] = (0.40, 0.55)` mirrors it exactly. Retuning
`d2-accuracy` in the JSON would therefore **silently** diverge from the constant with no test failure at
all. Whoever recalibrates it must update `SCORE_BANDS["accuracy"]` in the same change, and should add
`d2-accuracy` to the parametrize list so the next person cannot repeat the mistake.

**Update 2026-08-26 — Fix 11's code half is DONE (Gap 323). These are the exact numbers to mirror into the
JSON.** senior-dev has changed the two constants in `services/ops_recommendation.py::SCORE_BANDS`; the
workbook JSON is untouched and is still infra-devops's to change. The mirror direction is reversed for
these two fields only — everywhere else in this feature the tile is the source and the constant copies it,
but here the tile was the thing that was wrong, so **the constant is now the decision and the grid copies
it**:

| Panel | `thresholdsGrid` today | **Mirror it to** | Constant it must equal |
|---|---|---|---|
| `d1-latest-pass-rate` | red `< 0.20`, yellow `< 0.30` | **red `< 0.60`, yellow `< 0.75`** | `SCORE_BANDS["pass_rate"] = (0.60, 0.75)` |
| `d2-accuracy` | red `< 0.40`, yellow `< 0.55` | **red `< 0.75`, yellow `< 0.90`** | `SCORE_BANDS["accuracy"] = (0.75, 0.90)` |

Both grids keep their `== -1 → blue "n/a — see Detail"` row and their `Default → green` row unchanged;
only the two `<` rows' `thresholdValue`s move. Under the new bands tonight's real numbers grade the way
they should — verified by running the module, not by reading it: a 35-turn payload with `pass_rate=0.257`
and `accuracy_mean=0.600` now yields `pass_rate 0.257 red (below 0.60)` and `accuracy 0.600 red (below
0.75)`, where both were previously green.

*Why these numbers.* **accuracy (0.75, 0.90)** — accuracy is the only dimension graded against a
known-correct reference answer, so its bar is held above reference-free faithfulness's `(0.70, 0.85)`. The
red bound is anchored rather than picked: `services/agent_eval.py::decide_pass()` already requires
`accuracy >= ACCURACY_FLOOR = 0.70` on every single turn, so a run whose *mean* is under that floor means
the average turn is failing the gate outright — red starts just above it at 0.75. Yellow 0.90 is the
working target (about nine right answers in ten, with room for judge noise), deliberately short of
relevance's near-free 0.95. **pass_rate (0.60, 0.75)** — `decide_pass()` makes this the only *conjunctive*
number on the system: a turn passes only if faithfulness ≥ 0.80 **and** relevance ≥ 0.70 **and**
accuracy ≥ 0.70. That compounding is why its bar is not simply the highest here — three dimensions each
clearing their floor on ~90% of turns still lands the joint rate well under 0.90 with no regression at
all, so an 0.85-style bar would flag a healthy system nightly and be tuned out within a week. Green ≥ 0.75
means three turns in four are clean on all three checks; red < 0.60 means more than two in five fail a
required check. `pass_rate` therefore carries the **lowest yellow** in the band table but *not* the lowest
red.

*Three things infra-devops needs to know before touching the JSON:*

1. **The pin test is currently `xfail(strict=True)` on exactly these two params**, because the constant and
   the JSON genuinely disagree during the handover window. The moment the grid is mirrored those two
   XPASS, which pytest reports as a **failure** — that is intentional. The fix at that point is to delete
   the two `_AWAITING_JSON_MIRROR` markers and the transitional
   `test_the_two_recalibrated_bands_still_await_their_json_mirror` in `tests/test_ops_recommendation.py`;
   the ordinary pin then holds both bands going forward. Nothing else in that file should need to move.
2. **`d2-accuracy` is now in the parametrize list**, so from the next change onward it can no longer drift
   silently — the gap this doc flagged above is closed.
3. **There is a second, unpinned copy of these numbers**: `infra/alert-ai-eval-critical-only.bicep`
   (Gap 299) carries them as parameter defaults — `passRateRedBelow = '0.20'` and
   `accuracyRedBelow = '0.40'`, plus the same values written into the alert's `description` string and its
   header comment block. **No test pins that file**, so nothing goes red if it is forgotten; it would just
   keep paging on the old, far more permissive red bands while the tile says something else. It should be
   mirrored to `'0.60'` / `'0.75'` in the same infra pass. senior-dev deliberately did not touch it — it is
   bicep, and it needs a real deploy, which is infra scope.

**Implemented (Gap 322, 2026-08-26):** all three handover items closed. Both `thresholdsGrid`s mirrored to
the exact table above; `alert-ai-eval-critical-only.bicep`'s `passRateRedBelow`/`accuracyRedBelow` (plus the
`description` string and header comment) mirrored to `'0.60'`/`'0.75'` and redeployed — `az monitor
scheduled-query show` confirms the live query now reads `pass_rate < 0.60` / `accuracy < 0.75`. `d1`'s
n=3-run guard removed (the only panel the founder's top-level task named for guard removal — `d2-accuracy`/
`d3`/`d4`'s guards were deliberately left untouched, a narrower reading than this section's finding 3
argument for the whole of Section D). Backend suite re-run: the two `xfail(strict=True)` params XPASSed as
predicted, both markers and the transitional `test_the_two_recalibrated_bands_still_await_their_json_mirror`
removed, `pytest tests/test_ops_recommendation.py` → 84 passed, 0 xfailed. Live query proof against real
`law-invoicellm-dev` data: `d1` returns `pass_rate=0.167` (red under both old and new bands — this run
doesn't demonstrate the fix mattering); `d2-accuracy` returns `accuracy=0.625` — **red** under the new
`<0.75` band where it was **green** under the old `(0.40, 0.55)` band, which is the live proof the
recalibration changes real coloring, not just the constant.

### Explicitly OUT of scope for this redesign

Listed so it cannot be silently expanded. Each of these is real work; none of it is this task:

- **Scheduling `scripts/sweep_azure_cost.py` as a real Azure job.** Separate infra task. Fix 1 makes the
  staleness *visible*; it does not make the data fresh.
- **Scheduling Gap 305's online-signals job** (`scripts/emit_online_signals_job.py`, which still has no
  `Microsoft.App/jobs` resource). Blocked on the founder's still-open decision about the dead
  `budget_exhaustion_rate` signal. Fix 10's colouring change is *not* blocked on it and proceeds.
- **Actually fixing Dashboard Insights' latency** — pre-warming the cache, or moving generation to a
  background job. This redesign adds **observability only**; the fix is a separate future gap.
- **Any new production code change.** This redesign is workbook JSON + bicep only. The single exception
  that would force code — Fix 11's `SCORE_BANDS` constants — is called out above precisely so it gets its
  own gap rather than riding in unnoticed.

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
      caller-supplied-`--out` half, 2026-08-25). ~~Needs the pending backend image refresh to take effect live.~~
      **Correction 2026-08-26 (live-verified): live now** — image rebuilt 2026-08-25T14:41Z from `cb96d8f`,
      and `caj-benchmark-eval-dev`'s 2026-08-26T03:00 UTC run succeeded.
- `[x]` **(a)** Build the recommendation pass as a step in the nightly job's script — done 2026-08-25
      (Gap 318): `services/ops_recommendation.py` + a nightly-only `recommendation_pass_step()` in
      `scripts/run_agent_eval.py`, 3 categories, every band lifted from a live workbook panel and
      pinned to it by test, 68 new tests, no Azure call and nothing deployed
- `[x]` **(b)** Persist each run's recommendations somewhere a workbook can query (not Postgres) — done
      2026-08-25 (Gap 319): a new `ops_recommendation` custom event, one row per category per run
      (`telemetry.track_ops_recommendation()` + `ops_recommendation.mirror_recommendation_pass()`,
      wired into `recommendation_pass_step()`), bounded so `findings` stays valid JSON under Application
      Insights' 8,192-char property cap, 21 new tests, nothing deployed
- `[x]` **(c)** Add the Workbook panel that renders the latest run's recommendations — done 2026-08-26
      (Gap 320): plain-grid panel on both workbooks (25→27, 49→51 items), byte-identical query, deployed
      and pull-back-verified against `rg-invoice-llm-dev`; 0 rows today, correctly, until the pending
      backend image refresh — which, as corrected 2026-08-26, means the **further** refresh carrying
      Gaps 318/319 (last task below), not the 2026-08-25 one that already landed
- `[x]` Unblock deploys: `benchmark-gate` removed from `deploy-dev.yml` entirely (2026-08-25, Gap 312) — not fixed, per standing rule that CI/CD must never execute tests/benchmarks
- `[x]` ~~Grant `Monitoring Reader` to `id-invoicellm-dev` via a narrow template — not started~~
      **Correction 2026-08-26 (live-Azure-verified): done.** `infra/rbac-monitoring-cost-only.bicep` deployed
      (also grants Gap 297's `Cost Management Reader` in the same template); `id-invoicellm-dev` now holds
      7 role assignments, verified via `az role assignment list`. Closure test run as the managed identity
      via `az containerapp exec` into `ca-invoice-be-dev`: real Resource Graph + Insights/metrics reads
      succeeded with no 403. Gap 318's `container_health` category is not yet re-evaluated live — that needs
      `ops_recommendation.py` in a deployed image and a nightly run, which is separate follow-up work, not
      this grant.
- `[x]` ~~Deploy the pending backend image so Sections B/C and the GenAI dependency rows carry real data — not started~~
      **Correction 2026-08-26 (doc-reconciliation pass, live-verified): done.** Image rebuilt
      **2026-08-25T14:41Z from commit `cb96d8f`**; `AppEvents` now returns real `chat_turn` rows,
      `AppDependencies` returns `GenAI`/`az.ai.openai` rows, and `AppRequests` returns rows from the real
      container — so Sections B/C and the GenAI cross-check carry live data.
- `[x]` ~~Deploy a **further** backend image carrying Gaps 318 + 319 so the recommendation pass runs and
      Gap 320’s panel renders rows — not started; those two gaps are uncommitted, so no image contains them
      and `ops_recommendation` stays at 0 rows.~~ **Correction 2026-08-26 (redesign session): done.** Gaps 318/319/320
      are committed (`f9aa0c5`) and deployed, and the nightly run has produced real `ops_recommendation` rows, so both
      recommendation panels render live data. Commit state verified in-repo; the "real rows landed" half is the founder’s
      own 2026-08-26 observation, not a query run by this agent. See Fix 9 in the redesign section above.
- `[x]` **Workbook redesign — priority-ranked information architecture (2026-08-26)** — design approved by the founder,
      **implemented and deployed live 2026-08-26 (Gap 322)**. 3 tiers (Cost & Reliability → Extraction & Chat Quality → Cost Reduction) on both workbooks,
      recommendation cards moved inline per tier, plus the full 11-item panel fix list, all applied. Full spec in the section above;
      implemented by infra-devops (workbook JSON + bicep). Gap number assigned: **322**.
      Fix 11's code half was its own separate gap (**323**) because recalibrating `d1`/`d2-accuracy` forced a change to
      `services/ops_recommendation.py::SCORE_BANDS`, production code; both gaps are now closed.
- `[x]` **Fix 11 — `d1`/`d2-accuracy` band recalibration (Gap 323 code + Gap 322 JSON/bicep)** — **fully done**
      2026-08-26: `SCORE_BANDS["pass_rate"] = (0.60, 0.75)`, `SCORE_BANDS["accuracy"] = (0.75, 0.90)`,
      `d2-accuracy` in the pin test's parametrize list. Both `thresholdsGrid`s mirrored to the same values,
      `alert-ai-eval-critical-only.bicep`'s copy mirrored and redeployed. Backend suite: the two
      `xfail(strict=True)` params XPASSed as predicted, markers and the transitional test removed,
      `pytest tests/test_ops_recommendation.py` → 84 passed, 0 xfailed. See the Fix 11 update above for full
      live-query evidence that the new bands actually colour real data red.
