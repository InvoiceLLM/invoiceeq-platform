# Feature 20 / 23 / 24 — Implementation Status

Live status tracker for the Azure cost/health monitoring (F20), AI eval/observability (F23), and Ops
Digest Agent (F24) rollout scoped 2026-08-23. Updated as tasks complete — check here for current state
before asking; this is the source of truth, not the conversation history.

**All 7 blocking decisions resolved 2026-08-23**: Workbooks for delivery, GPT-4o approved, Ollama done
(llama3.2:latest, smoke-tested, config fixed), digest shares the critical channel, Gap 290 = CPU+memory
85% threshold, Gap 291 = keep shared channel (no new escalation), Track 1 benchmark = synthetic with
artifacts kept for architect/BA review.

## Legend
`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

## Wave 1 — no dependencies, running now

| Task | Feature | Owner | Status | Notes |
|---|---|---|---|---|
| Gap 290 — CPU+memory 85% scale rules | F20 | architect (direct) | `[x]` | Done 2026-08-23. Real root cause found: bicep already had well-reasoned scale rules authored (invoice-be even had an existing CPU rule at 70%) but NONE were ever actually deployed (`rules: null` live on all 3 apps despite source). Fixed bicep source + applied live via YAML patch (not a full `08-apps.bicep` deploy, which would roll back stale image tags per known `params.dev.json` drift). invoice-be/fe: HTTP + CPU 85% + memory 85%. invoice-website: kept its existing HTTP-only rule (50 concurrent) since CPU/memory rules require minReplicas>=1, and source declares website's dev default as scale-to-zero (0) — though live minReplicas is actually already 1, a separate small drift noted but not fixed here. All verified live via `az containerapp show`. |
| GPT-4o deployment | F23 | architect (direct) | `[x]` | Done 2026-08-23. `gpt-4o` version `2024-11-20` (latest GA, comfortably clears the 2024-08-06+ strict-mode structured-output requirement), GlobalStandard SKU, 10K TPM capacity. New `infra/gpt4o-deployment.bicep`, `what-if` confirmed 1-create/0-modify before deploy, `provisioningState: Succeeded`. Deployment name: `gpt-4o` |
| Correction-rate / alert-precision rollup queries | F23 | architect (direct) | `[x]` | Done 2026-08-23. `services/extraction_quality_rollup.py` — reads the existing `AuditLog.details` audit trail (no new event logging needed), 6 tests passing. Not yet wired to a dashboard panel |
| F24 two-tier routing logic | F24 | architect (direct) | `[x]` | Done 2026-08-23. `services/ops_digest_routing.py::classify()`, 11 tests. Caught + fixed a real bug in dev (full-outage check fired on any replica shortfall, not just true zero-replica outage). Full-outage exception is scaffolding — no real "replicas down" data source exists yet |
| Cost Management API integration | F20 | senior-dev | `[x]` | Done 2026-08-23. `services/azure_cost.py`, `scripts/sweep_azure_cost.py`, 40 tests. Verified against real live Azure (16,513.97 INR MTD spend, 3 dimensions reconciled). **Found Gap 297** (RBAC role assignment written, not deployed — managed identity has never actually authenticated; renumbered from a duplicate "Gap 294") **and Gap 295** (budget alert was broken: set to 150 assuming USD, account bills in INR, already at 10,935% of budget, both notifications permanently fired — **fixed 2026-08-23**, founder set ₹20,000/month against the real ~23,880 INR forecast, 50/75/95% actual thresholds, `infra/10-budget.bicep` updated with a namingPrefix override note — not yet deployed) |
| Fix API request telemetry (currently empty) | F20 | senior-dev | `[x]` | Done 2026-08-23 (Gap 292). Root cause: Python import-order trap in `main.py` — `FastAPI` imported before `configure_azure_monitor()`'s class-swap instrumentation ran, so no request span was ever created, silently. Fixed via explicit `FastAPIInstrumentor.instrument_app()`. Verified live: 0 → 4 real `AppRequests` rows. **Not deployed to `ca-invoice-be-dev` yet.** Open: `AppRoleName` is `unknown_service` for every container (no `OTEL_SERVICE_NAME` set) — needs a decision before Area 2 panels |
| Extend telemetry to Trainer/EVOLVE, Dashboard insights, QA-summary | F23 | senior-dev | `[x]` | Done 2026-08-23 — all 5 call sites already had telemetry; real gap was missing tests (9 added), registry table corrected |
| Track 1 benchmark — synthetic seeded/clean documents | F23 | senior-dev + functional-tester | `[x]` | Done 2026-08-23. 13 seeded cases, alert recall 100% (13/13), clean-doc false-positive rate 25% (1/4) — found real cause (**Gap 293**, unfixed: outbound discount has nowhere to go in the schema, always false-positives). Live gpt-5-mini: 100% field accuracy/81 fields. Artifacts in `docs/extraction_benchmark/` for architect + BA review |
| Track 2 benchmark — extend chat case set, 5-metric judge | F23 | senior-dev | `[x]` | Done 2026-08-23. 11→20 cases, judge calls 97→60 while scoring 3 more metrics. **Found Gap 294** (unfixed): chat pastes raw SQL into user-facing answers, one case showed fabricated SQL referencing a nonexistent table. Honest caveat: run-to-run non-determinism (~0.07) exceeds the signal being measured in a same-vs-combined comparison — correctly not overclaimed. **Both tracks confirmed blocked by the known `.dockerignore` issue** — neither can run in the deployed container yet |
| Model comparison harness (provider override flag) | F23 | senior-dev | `[x]` | Done 2026-08-23. `--provider`/`--model`/`--api-version`/`--persist-candidate` on `run_agent_eval.py`; judge stays fixed regardless of candidate (verified). Also fixed `QueryRoutingSchema.route` to a real `Literal` enum — verified on live gpt-5-mini, 0 validation errors, but honestly measurably shifts routing on *ambiguous* questions (not a pure no-op). **Ollama comparison unverified** — no server running to test against, and `.env` overrides `OLLAMA_MODEL` to `qwen2:0.5b`, silently bypassing the `llama3.2:latest` fix — flagged, not touched. Found a pre-existing tracker "Gap 294" numbering collision from concurrent work, used 296 instead |
| Gap 291 | F20 | — | `[x]` | Decided: keep shared channel, no code change needed |

## Wave 2 — starts once Wave 1 dependencies clear

| Task | Feature | Owner | Status | Depends on |
|---|---|---|---|---|
| Cost + Health Workbook | F20 | infra-devops | `[x]` | Done and deployed 2026-08-23. Single-page workbook, 12 data panels + 2 honest limitation panels (extraction quality needs Postgres, no workbook data source can reach it; CI/CD gate is GitHub Actions state, same issue). Schema-validated against Microsoft's live schema + cross-checked against 710 real shipped templates; every query run live before being written in. No interactive portal access exists in this environment — query correctness verified, visual rendering was not and cannot be from here |
| Nightly + pre-deploy-gate scheduler | F23 | infra-devops | `[~]` | Code done 2026-08-23. `.dockerignore` fix done by extracting benchmark code into a new `benchmarks/` package (ships with the image; `tests/` stays excluded) — found + fixed a transitive `reportlab` dev-dependency gap along the way by pre-generating and committing the two PDF fixtures it needed. Re-run full suite: 1248 passed, same 3 pre-existing failures. `infra/benchmark-eval-job-only.bicep` (narrow standalone, same Gap-298 workaround pattern) what-ifs clean — 1 create/50 ignore — sized off a real measured live run (5400s timeout). Pre-deploy CI gate written (`deploy-dev.yml`, blocks deploy on Track 1 `--mode verify` + a 5-case Track 2 smoke subset). **Verified in a real built container 2026-08-23** (`docker build -f docker/Dockerfile.be`, image `invoice-be-verify:nightly`, 3.12GB): `benchmarks/` present and importable, `tests/` absent — fix confirmed working, not just re-read. Track 1 ran for real inside the container: exit 0, 13/13 recall, 25% clean-FP (Gap 293, tolerated) — matches doc exactly. Track 2 5-case smoke ran for real against live dev Azure OpenAI (~10min, exit 0, 0 errors) and the exact `deploy-dev.yml` jq gate logic was reproduced against the real output — passes as designed (gate is error-only, not score-threshold, by design). **Still not deployed** — the fix itself (`benchmarks/__init__.py` and most of the package, plus scripts/config/workflow changes) is uncommitted/untracked; a CI run or standalone bicep deploy right now would check out stale `HEAD` (`f8abe77`) and fail exactly as before. Needs commit (+ push, on explicit instruction) before either the CI gate or `benchmark-eval-job-only.bicep` can work for real. **Result mirror added 2026-08-24** — before either cadence's first live run, both tracks now emit an aggregate custom event (`extraction_benchmark_run`, `agent_eval_summary`) and upload their full raw JSON to blob, because neither track's results could previously be queried by anything (`--no-write` discards Track 1's artifacts, `--no-persist` meant a gate run emitted nothing, and a workbook cannot read stdout). `telemetry.py` + new `services/benchmark_artifacts.py` + `--run-label`/`--no-mirror` on both scripts, wired into both callers. Three findings: **no benchmark script ever called `configure_azure_monitor()`**, so nothing from either job has ever reached `customEvents` (fixed for the mirror's own events; per-call `llm_agent_call` events deliberately left alone pending an ingestion-cost decision); **`benchmark-artifacts` container does not exist** on `stinvoicellmdev2` — created on first use at runtime, declaring it in `storage.bicep` flagged as a decision; **RBAC needed nothing** (`Storage Blob Data Contributor` already granted at account scope, verified live). 29 new tests + 2 CLI non-fatality tests, 336 passed across affected files, both bicep templates compile, both scripts smoke-run for real. **No workbook panel reads either event yet** |
| Digest scheduler + LLM-summarization job | F24 | senior-dev + infra-devops | `[~]` | Code done 2026-08-23 (`services/ops_digest_collect.py`, `ops_digest.py`, `ops_digest_delivery.py`, `scripts/ops_digest_job.py`, 56 tests, full suite 1304/3-pre-existing-fail/7-skip). Cadence decided: every 6h (`0 1,7,13,19 * * *` UTC = 06:30/12:30/18:30/00:30 IST), window matches schedule exactly. Two real live dry-runs against 72h of real alert data — one surfaced a genuine design fix (self-resolved history now passed to the LLM as context, else it can't tell "recurring" from "isolated"). **Not deployed** — re-verified 2026-08-23 after the disk crisis cleared: `ops-digest-job-only.bicep` what-if re-confirmed clean (1 create/50 ignore) against live `rg-invoice-llm-dev`, and a real local Docker build confirms all 4 digest files are present and import cleanly in the built image (code itself is deployable, no rework needed there). Two independent blockers remain, both real, neither fixed yet: (1) all 4 files are still untracked (`git status --porcelain` confirms) so the ACR image doesn't contain this code — needs commit + push + CI build; (2) live RBAC check confirms `Monitoring Reader` is genuinely not granted to `id-invoicellm-dev` (5 other roles are), and a plain redeploy of Stage 7 (`07-rbac.bicep`) would fail before reaching that assignment — its default `namingPrefix` resolves to `stinvoicellmdev`, which `az storage account show` confirms doesn't exist (live is `stinvoicellmdev2`); fixing this needs either a `namingPrefix` override on that deployment or narrow-scoping just the Monitoring Reader assignment (same pattern as the standalone job bicep). Found **Gap 298** (Stage 8/`08-apps.bicep` unrunnable against dev — image + naming-prefix drift, unrelated to this feature) and **Gap 299** (AI-eval criticals currently page nobody — digest names them explicitly rather than silently treating them as already-handled). Full-outage exception still dormant, no data source computes it yet. Budget line item off by default (Gap 295 — budget already permanently breached, would be a guaranteed noise line) |

## Wave 3 — after Wave 2

| Task | Feature | Owner | Status | Depends on |
|---|---|---|---|---|
| Verify digest quality against real fired alerts | F24 | functional-tester | `[ ]` | Digest scheduler built |

## New gaps found during Ops-page field-by-field review (2026-08-24)

**Reconciled into the tracker 2026-08-24** — Gaps 300 and 301 below now have proper entries in
`be_features_tracker.md` (the single source of truth for gap numbering per `.claude/CONVENTIONS.md`);
they previously existed only in this file. Four further Feature 23 gaps were filed at the same time
from this session's code-level findings: **Gap 302** (no Trace-level capture), **Gap 303** (no
Thread-level capture / drift detector), **Gap 304** (every tile field single-sourced, not
dual-sourced) and **Gap 305** (`emit_online_signals()` has zero callers).

**Gap 300** — Azure OpenAI/LLM calls are not tracked in `AppDependencies` telemetry.
Confirmed live via direct KQL against `law-invoicellm-dev`: zero rows match `openai` in
`Type`/`Target`/`Name` across the last 30 days, while Postgres (54K calls), Storage Queue
(183K+ calls), Blob storage, and Document Intelligence are all solidly instrumented in the
same table. LLM calls are almost certainly the dominant latency source for the Chat and
Ingestion & Extraction feature areas — without this instrumentation, a dependency-time
breakdown would either miss LLM time entirely or misattribute it as "app logic" time (the
gap between total request duration and the sum of tracked dependencies).
**Depends on this gap being closed**: the proposed "API perf: dependency-time breakdown
per feature area, with recommendation text generated from whichever dependency dominates"
build item (raised during the Ops-page field review) — that feature cannot give a correct
answer for LLM-heavy areas until Azure OpenAI calls are actually tracked as dependencies.

**Fixed 2026-08-24, not yet deployed.** Both options in the gap's own suggested fix were
checked against the real installed packages first. **Option (a) rejected on evidence**:
`pyproject.toml`/`uv.lock` carry only the django/fastapi/flask/logging/psycopg2/requests/
urllib/urllib3 instrumentations `azure-monitor-opentelemetry` 1.8.9 pulls in — there is no
`opentelemetry-instrumentation-openai(-v2)`, `openinference` or `traceloop` in the lock at
all, so enabling one means a new dependency pinning its own
`opentelemetry-instrumentation` (0.64b0, owned by the Azure distro), and it patches the
`openai` SDK client only, covering neither the `ollama` provider nor `MockInvoiceLLM`.
**Option (b) taken**: `telemetry.py` now opens one `SpanKind.CLIENT` span per LLM call from
inside `tracked_llm_call()` — the wrapper already present at every real call site, so **no
call site changed**. New: `resolve_gen_ai_system()` (→ `az.ai.openai` / `ollama` / `mock`,
reusing `resolve_model_name()`'s mock detection so a fabricated call is never labelled as a
real one), `resolve_gen_ai_peer()` (endpoint **hostname only** — the configured endpoint's
query string is where `api-version`/keys travel), `_start_llm_dependency_span()` and
`_end_llm_dependency_span()`. The span carries `gen_ai.system`/`gen_ai.operation.name`/
`gen_ai.request.model`/`peer.service`/`server.address` plus `agent_name`, `tenant_id`,
`request_id`, and — set at close, when they're known — `gen_ai.usage.input_tokens`/
`output_tokens`/`llm_calls`. Exporter contract read off the installed
`azure-monitor-opentelemetry-exporter` **1.0.0b56** rather than assumed: a CLIENT span
exports as `RemoteDependencyData` (the `AppDependencies` table), `gen_ai.system` sets
`DependencyType = "GenAI | {value}"` (`_GEN_AI_ATTRIBUTE_PREFIX`, `_exporter.py:120`) and
takes precedence over the HTTP/DB branches, `peer.service` sets `DependencyTarget`.
Fails closed like every other emitter here — the start path returns `None` on any
exception and the end path ends the span from its own `finally`, so a span failure can
never raise into an agent call. **Verified by execution**: 9 new tests in
`tests/test_telemetry.py` against a real OTel SDK `TracerProvider` + in-memory exporter
(full file 23 passed; adjacent `test_query_tools`/`test_agentic_sage`/`test_agent_eval`/
`test_ops_digest` 277 passed; `ruff` clean), including one that runs the recorded span
through the exporter's own `_convert_span_to_envelope` and asserts
`RemoteDependencyData` / `type = "GenAI | az.ai.openai"` / `target =
"oai-invoicellm-dev.openai.azure.com"`, and one that asserts the span is a **child of the
surrounding request span** — the parent link that makes the dependency-vs-request
breakdown possible at all. **Not deployed** — same blocker as Gap 292's fix; live
`AppDependencies` keeps returning zero GenAI rows until a backend image carrying this
code ships. First live check after that deploy: `AppDependencies | where TimeGenerated >
ago(1h) | summarize count() by DependencyType` should gain a sixth kind.

**Gap 301** — CPU-high and memory-high alerts (`alert-rules.bicep`) fire on a 15-minute
averaged threshold alone (CPU > 90%, memory > 85%), with no check on whether autoscale
(Gap 290, also triggers at 85% for both) actually could have resolved it. Confirmed live:
both alerts already use `windowSize: 'PT15M'` specifically to let autoscale stabilize
first — so brief autoscale-then-resolve blips are already filtered by the time window —
but a *sustained* 15-minute elevation still fires even if autoscale correctly scaled out
and is simply still catching up, not stuck. Founder wants these to fire only when
autoscale is genuinely maxed out and still insufficient, not just "elevated a while."
**Fix**: add a second required criterion (`AllOf`) to each alert — `Replicas ==
maxReplicas` alongside the existing CPU/memory threshold — so it only fires when
autoscale has hit its ceiling and the condition still hasn't cleared. **Fixed
2026-08-24, not yet deployed.** `modules/monitoring/alert-rules.bicep`'s `cpuAlerts`/
`memoryAlerts` `[for app in containerApps: ...]` loop now carries a `maxReplicas` field
per app (5 new params: `backendMaxReplicas`/`workerMaxReplicas`/`frontendMaxReplicas`/
`chromaDbMaxReplicas`/`websiteMaxReplicas`, defaults matching `08-apps.bicep`'s/
`modules/data/chromadb.bicep`'s own maxReplicas defaults — this stage deploys
independently of Stage 8 so they're separate params, not a cross-stage output, kept in
sync by hand), and each alert's `criteria.allOf` gained a second criterion:
`{ name: 'ReplicasAtMax', metricName: 'Replicas', operator: 'GreaterThanOrEqual',
threshold: app.maxReplicas, timeAggregation: 'Maximum' }`. `09-monitoring.bicep` threads
the same 5 params into the `alertRules` module call. `az bicep build` clean on both
files. `az deployment group what-if -g rg-invoice-llm-dev --template-file
09-monitoring.bicep` (filtered params matching `deploy-all.ps1`'s own
`New-StageParamArgs` pattern) returned `Succeeded`, 22 Modify / 22 Create / 31 Ignore,
75 total — all 10 CPU/memory alerts show `Modify` with `properties.criteria.allOf`
gaining the new `ReplicasAtMax` criterion (confirmed threshold `5` on
`alert-ca-invoice-be-dev-cpu-high`, matching `backendMaxReplicas`'s default). The other
deltas on those same resources (`properties.actions` action-group id, `properties.
windowSize` PT5M→PT15M) are pre-existing drift from this session's earlier
dual-action-group/90%-threshold/PT15M-window edits, already in the file before this
gap's fix and unrelated to it — the live dev alerts simply haven't been redeployed since.
**Not deployed** — `az deployment group create` was deliberately not run.

## Cost & Health workbook — 4 manual edits from the field-by-field review, validated 2026-08-24

During the founder's field-by-field Ops-page review that surfaced Gaps 300/301 above, four
edits were made directly to `infra/monitoring/cost_health_workbook.json` (the source
`az bicep build`-loaded by `infra/workbook-cost-health-only.bicep` via `loadTextContent`):

1. Removed the `extraction-quality-header` text panel outright — that content belongs to
   Feature 23's own (future) workbook, not this one.
2. Removed the `cicd-header` text panel outright and permanently — founder already gets
   CI/CD gate alerts directly from GitHub, this was a redundant view.
3. Edited the `header` panel's honesty table: removed the two rows for the panels above,
   added a dated "2026-08-24 update" note explaining both removals.
4. Replaced the `alerts-table` full detail-table panel with a single-value count query
   (`alertsmanagementresources | ... | summarize AlertsFired24h = count()`, `ago(24h)`),
   retitled to explain why it was shrunk.

**Validated 2026-08-24**, structural-only (the KQL queries in the untouched items were not
re-run — only the 4 edited regions were checked):
- `JSON.parse` on the full file: valid JSON, no syntax errors from the manual edits.
- `az bicep build --file infra/workbook-cost-health-only.bicep`: compiles clean (note:
  `loadTextContent` embeds the file as a raw string at compile time — bicep build alone
  does not itself parse/validate the JSON, hence the separate JSON.parse + schema checks).
- Re-derived the original build's schema-validation approach (the `ajv`-against-Microsoft's-
  live-`schema/workbook.json` check the doc line below already referenced): downloaded
  `microsoft/Application-Insights-Workbooks`'s current `schema/workbook.json` fresh and ran
  `ajv` (installed fresh, not reused from any repo state) against the full file — **0
  errors**. Did not re-clone the 710-template shipped-example corpus this time since no new
  item *shapes* (KQL step, param step, ARG step) were introduced — the edits only removed
  two items and replaced one query/title, reusing shapes already in the file and already
  cross-checked in the original build.
- Confirmed structurally: `extraction-quality-header` and `cicd-header` no longer appear
  anywhere in the file (neither as an item `name` nor referenced elsewhere); `header`'s
  markdown contains the "2026-08-24 update" note; `alerts-table` now holds the single
  `AlertsFired24h` count query with the expected title text.

## Already done (prior to this rollout)

- Ollama installed, config fixed (`llama3.2:latest`), smoke-tested, stopped — 2026-08-23
- Feature 23 full rescope + Feature 20 area 1/2 plan + Feature 24 design doc — pushed
- Gaps 288, 289 (autopilot, scrollbar) — fixed, pushed
- Old Feature 23 build (9 workbooks, golden bank, nightly job) — deleted from Azure + repo
