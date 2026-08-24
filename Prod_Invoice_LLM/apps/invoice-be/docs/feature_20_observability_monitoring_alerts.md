# Feature 19: Enterprise Observability, Container Health & Operational Alerting

Production-grade observability, automated container health lifecycle management, structured JSON telemetry, Dead-Letter Queue (DLQ) isolation, visual Azure Workbook dashboards, and multi-channel alerting across the Invoice AI SaaS platform in Azure (`rg-invoiceai-prod`).

---

### 2026-08-23 — Rethink: this feature is now the home for "Azure Cost" and "Azure Health/Performance"

The founder and architect scoped a 3-area monitoring redesign this day: (1) Azure cost & optimization, (2) Azure resource health/performance & optimization, (3) AI agent eval & observability. **This feature (19/20) now owns areas 1+2**; area 3 stays scoped to Feature 23. The dashboard content below (workbooks, some alert-rule detail) was found to be partially aspirational — much of it describes a design, not a verified-live state — so treat the sections below as historical/target design, and this section as the current source of truth on what's actually confirmed live and what's planned next.

**Verified live, reusable as-is:**
- 25 metric alerts (`alert-rules.bicep`) covering per-container CPU/memory/restart-loop, Postgres CPU/storage/connections, storage availability, DLQ poison messages, Doc Intelligence/OpenAI client errors — solid, comprehensive.
- A cost budget (`10-budget.bicep` → `budget-invoicellm-dev`) already exists live — Area 1 is not starting from zero, this piece carries over.
- Native Azure Monitor metrics for Container Apps / Postgres / Redis need no new instrumentation for Area 2's status panels.

**Verified live, real gaps found (tracked as Gap 290, Gap 291, Gap 292):**
- `invoice-be`/`invoice-fe`/`invoice-website` run on Azure's un-tuned default HTTP concurrency scale rule (~10 concurrent req/replica) — never deliberately configured. Only `queue-worker` has a real, tuned rule (queue depth ≥ 15).
- The critical/info alert severity split is correct in the bicep, but both action groups (`ag-invoicellm-dev`, `ag-invoice-llm-dev`) notify the identical email + Teams channel — no actual destination differentiation today.
- ~~App Insights request auto-instrumentation (`AppRequests`) is empty — zero rows for any route, any time window — despite the connection string being wired in. API performance monitoring has no usable data source yet.~~ **Fixed same day (Gap 292 / Task 19.10, see the 2026-08-23 section below).** Root cause was a Python import-order trap in `main.py`, not missing configuration. Request telemetry now produces real `AppRequests` rows with templated route names, status codes and durations — verified against the live `appi-invoicellm-dev`, though not yet deployed to `ca-invoice-be-dev`.

**Area 1 (Cost) — plan:** total spend trend + spend-by-service/resource + forecast-vs-budget, from Cost Management API (new plumbing, separate from App Insights/Log Analytics). Optimization signals: idle/low-utilization resources (cross-referenced with Area 2), cost per invoice processed, day-over-day spend anomaly. **Data plumbing built 2026-08-23 (Task 19.11) — see the dedicated section below.** Total spend trend, spend-by-service, spend-by-resource-type, forecast-vs-budget and the day-over-day anomaly figure are all live and queryable in `appi-invoicellm-dev` today. Still not built: idle/low-utilization detection (needs Area 2's metrics to cross-reference) and cost-per-invoice-processed (needs a join against Postgres invoice counts, which no workbook can do — it belongs in the Ops Digest Agent, not in this module).

**Area 2 (Health/Performance) — plan:** container status, DB status (Postgres + Redis), DLQ, CI/CD gate, scaling status — plus a small "recent alerts" panel reusing the existing `alertsmanagementresources` Resource Graph query pattern. ~~API performance panel blocked on fixing request auto-instrumentation first.~~ **Unblocked 2026-08-23 (Task 19.10)** — `AppRequests` now carries per-route latency/status data. API grouping for that panel: Ingestion & Extraction, Chat, Review & Correction, Autopilot & Connectors, Dashboard & Reporting, Trainer, Billing & Admin, Auth; the `case()`-over-`AppRequests.Name` KQL that implements it is given below and has been run against live rows.

**Decision:** don't patch the existing `dashboard.bicep` workbook (6 panels, described below, never actually deployed) or today's AI Control Tower workbook split — rebuild fresh Cost and Health/Performance workbooks once this plan is confirmed, reusing proven KQL patterns and the `loadTextContent()` bicep deploy mechanism where they fit.

---

### 2026-08-23 — `AppRequests` fixed: root cause was an import-order trap, not missing instrumentation

This is the resolution of the third gap listed above, tracked as **Gap 292 / Task 19.10**. It unblocks the Area 2 "API performance" panel.

#### What was actually wrong

The instrumentation was already wired. `main.py` called `configure_azure_monitor(connection_string=..., logger_name="invoice_be_telemetry")` at import, `azure-monitor-opentelemetry` was in `pyproject.toml`, and that distro ships `opentelemetry-instrumentation-fastapi` as a hard dependency. Everything *looked* right, which is why this survived so long.

The trap is in **how** the distro turns FastAPI instrumentation on. `FastAPIInstrumentor._instrument()` does not patch a function — it rebinds a module attribute:

```python
def _instrument(self, **kwargs):
    self._original_fastapi = fastapi.FastAPI
    fastapi.FastAPI = _InstrumentedFastAPI      # subclass whose __init__ calls instrument_app(self)
```

That only affects app objects constructed from `fastapi.FastAPI` **after** the swap. `main.py` reads:

| line | statement | effect |
|---|---|---|
| 6 | `from fastapi import FastAPI, status` | copies the **original** class into `main`'s namespace |
| 22–36 | `configure_azure_monitor(...)` | rebinds `fastapi.FastAPI`, but **not** `main.FastAPI` |
| 84 | `app = FastAPI(...)` | resolves the stale local name → plain, un-instrumented app |

So no OTel ASGI middleware was ever installed, no `SERVER` span was ever created, and `AppRequests` stayed empty forever. The failure is silent by construction: nothing errors, `configure_azure_monitor` reports success, and the app serves traffic normally.

The decisive corroboration is the **shape** of what was missing. Every other instrumentor the distro enables (psycopg2, requests, urllib, urllib3) patches at the call site rather than swapping a class, so those were unaffected — and the same workspace holds **508,374 `AppDependencies` rows over 7 days** sitting next to **0 `AppRequests`**. Only the class-swap-based instrumentor failed, exactly as this root cause predicts.

A second, quieter casualty: `TracingAndLoggingMiddleware.dispatch` reads `trace.get_current_span()` to stamp `trace_id` on every JSON access log. With no span in scope that read always failed its `is_valid` check and fell through to the `request_id` uuid4 fallback — so the "trace correlation" the structured logs advertised never actually joined to anything in App Insights.

#### The fix

`main.py` records whether the distro initialised (`azure_monitor_configured`) and then, after the app and its middleware are constructed, calls:

```python
FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")
```

`instrument_app()` is the ordering-independent API — it wraps *this instance's* `build_middleware_stack`, so the OTel middleware ends up outermost over the whole user middleware stack no matter when it is called relative to the import. It is idempotent (guards on `_is_instrumented_by_opentelemetry`), so it stays safe if a future distro version starts catching this app some other way. This was preferred over simply reordering the imports, because reordering leaves a landmine: any later edit that moves the `from fastapi import FastAPI` line back above the distro init would silently re-empty the table.

`/health*` is excluded deliberately. ACA startup/liveness/readiness probes poll it roughly every 5s per replica, which would dominate request volume and distort the latency and error-rate panels this telemetry exists to feed; probe health is already covered by ACA replica state and the container metric alerts. This mirrors the `/health` skip `TracingAndLoggingMiddleware` already applies to access logs.

#### What this gives the Area 2 API performance panel

`AppRequests.Name` now carries the **templated** route (`GET /api/v1/invoices`, not the concretised path), which is the grouping key the 8 feature areas need. This KQL was run against live rows and returns correctly:

```kusto
AppRequests
| extend Area = case(
    Name has '/invoices' or Name has '/email-ingestion', 'Ingestion & Extraction',
    Name has '/chat',                                    'Chat',
    Name has '/audit',                                   'Review & Correction',
    Name has '/autopilot' or Name has '/connectors',     'Autopilot & Connectors',
    Name has '/dashboard',                               'Dashboard & Reporting',
    Name has '/trainer',                                 'Trainer',
    Name has '/billing' or Name has '/admin',            'Billing & Admin',
    Name has '/settings/security' or Name has '/auth',   'Auth',
    'Other')
| summarize Requests = sum(ItemCount),
            P95ms    = round(percentile(DurationMs, 95)),
            ErrorRate= round(100.0 * sumif(ItemCount, Success == false) / sum(ItemCount), 1)
  by Area
```

**Use `sum(ItemCount)`, never `count()`.** `azure-monitor-opentelemetry` 1.8.9 defaults to `RateLimitedSampler{5.0}` (≈5 traces/sec/replica, confirmed by reading the configured provider's sampler) — `ItemCount` is the per-row sampling weight that makes counts and error rates come out right. Latency percentiles are computed over sampled rows.

#### Verified / not verified

**Verified against real Azure:**
- Baseline independently reconfirmed: `AppRequests | summarize count()` over `P90D` against workspace `law-invoicellm-dev` → **0**.
- The real `main.py` app run against the **live** `appi-invoicellm-dev` connection string moved that to **4 rows**, carrying `GET /`, `GET /api/v1/invoices`, `GET /api/v1/chat/sessions`, `GET /api/v1/settings/security/api-key/verify` with `ResultCode` 200/500/401, matching `Success` flags and real `DurationMs` (2ms … 4091ms). Tagged `AppRoleName = invoice-be-local-f20-verify` so they are filterable from container traffic.
- **Zero `/health` rows** among them — the probe exclusion works live, not just in theory.
- The feature-area KQL above executed against those live rows.
- `APPLICATIONINSIGHTS_CONNECTION_STRING` confirmed present on `ca-invoice-be-dev` as a plain env var, instrumentation key matching `appi-invoicellm-dev`.

**Verified locally:** with an in-memory span exporter tapping the configured provider, 8/8 requests across all 8 feature areas produced `SERVER` spans (including 500s from DB-unavailable paths and a 401, so error-path telemetry is covered) and 0/2 health-probe requests did. `app._is_instrumented_by_opentelemetry` is `True` on the real `main.app`. Backend suite: **1003 passed, 3 failed, 6 skipped** — the 3 failures are two `redis.exceptions` connection errors and one `post_chat_message()` signature drift in `tests/test_rag.py`, none related; the new code path is gated on `azure_monitor_configured`, which is `False` throughout the suite (no test and no local `.env` sets the connection string), so this change cannot have caused them.

**Not verified:** the fix is **not deployed**. `ca-invoice-be-dev` still runs the pre-fix image, so `AppRequests` from the actual container stays 0 until a deploy. No automated regression test guards the import-order trap — worth adding to `tests/` (functional-tester scope) since the failure mode is silent.

#### Adjacent findings, not fixed here

- **`AppRoleName` is `unknown_service` for every container.** No `OTEL_SERVICE_NAME` / cloud-role-name is set in the compute bicep, so App Insights cannot distinguish `invoice-be` from `queue-worker` in any panel. Infra scope; needs a decision before the Area 2 panels are built.
- **Two stale claims corrected in `be_features_tracker.md`.** The Feature 23 Phase 2 entry states `APPLICATIONINSIGHTS_CONNECTION_STRING` "is still not set as a Container App secret" (it is set, as a plain env var) and that `customEvents` has 0 rows over 90 days (`AppEvents` now returns 36).
- **`queue_worker/main_worker.py` is unaffected.** It calls `configure_azure_monitor` too, but it is not a FastAPI app and never produced `AppRequests` by design; its telemetry is custom events and logs.

---

### 2026-08-23 — Area 1 (Cost) built: real Azure spend, from the Cost Management API

Tracked as **Task 19.11**; findings filed as **Gap 294** and **Gap 295**.

#### What was missing

The only "cost" telemetry this application had was Feature 23's `llm_agent_call` custom events, which measure LLM *tokens*. Measured through the new module on this day, tokens ("Foundry Models") are **461.71 INR of a 16,513.97 INR month-to-date bill — about 2.8%**. Container Apps (8,490.34), PostgreSQL (3,123.64), Container Registry (2,842.33), Redis (735.28) and Log Analytics (605.65) are the actual spend, and none of it was visible to this application in any form.

#### What was built

* **`apps/invoice-be/services/azure_cost.py` (NEW)** — direct REST against three ARM endpoints, all confirmed live before the code was written, not read off documentation:
  * `POST {rgScope}/providers/Microsoft.CostManagement/query?api-version=2023-03-01` — `get_month_to_date_daily_spend()` (Daily/MonthToDate), `get_daily_spend(days)` (Daily/Custom rolling window), `get_spend_by_dimension(dimension)` (granularity `None` + a `Dimension` grouping, used for both `ServiceName` and `ResourceType`).
  * `POST {rgScope}/providers/Microsoft.CostManagement/forecast?api-version=2023-03-01` — `get_month_end_forecast()`. **`timeframe: MonthToDate` is rejected by this endpoint** even though the query endpoint accepts it (`BadRequest: Invalid dataset grouping: 'BillingPeriod'`); `Custom` with explicit month bounds is the shape that works, and `test_forecast_never_uses_month_to_date` is the regression guard.
  * `GET {rgScope}/providers/Microsoft.Consumption/budgets/{name}?api-version=2023-11-01` — `get_budget_status()`, reading the live `budget-invoicellm-dev` that `infra/10-budget.bicep` deploys. It returns `amount`, `currentSpend` **and** `forecastSpend` in one call, so forecast-vs-budget does not depend on the forecast endpoint succeeding. Api-version deliberately pinned to the same value as the bicep so reader and writer cannot drift.
  * `collect_cost_snapshot()` assembles all of it into a `CostSnapshot` (`DailySpend`, `SpendSlice`, `BudgetStatus`, `MonthEndForecast` dataclasses, all with `to_dict()`), recording per-section failures on `snapshot.errors` rather than raising — a throttled fifth call must not discard four successful ones.
  * `CostSnapshot.day_over_day_change_pct` compares days **-3 and -2, not -2 and -1**: Azure's most recent usage day is always partial and still accruing, so comparing it against a finished day reports a fabricated collapse in spend every morning.
  * Auth (`_acquire_token`, `_fetch_managed_identity_token`, `_fetch_cli_token`): explicit token → managed identity (Container Apps' `IDENTITY_ENDPOINT`/`IDENTITY_HEADER`, then IMDS, with `AZURE_CLIENT_ID` selecting the user-assigned identity) → Azure CLI, the last one **off by default** behind `AZURE_COST_CLI_FALLBACK`. Implemented on `httpx` (already a dependency) rather than adding `azure-identity` + `azure-mgmt-costmanagement`: this repo had *no* managed-identity Python code at all before today, and two new SDKs plus a `uv.lock` regeneration for three HTTP calls was not worth it. `_fetch_managed_identity_token()` is the single seam to swap for `ManagedIdentityCredential` later.
  * `_request_with_retry()` treats **429 as routine, not exceptional** — roughly half the exploratory calls made while building this were throttled — honouring `Retry-After`/`x-ms-ratelimit-microsoft.costmanagement-*`. 401/403 is raised immediately with a message naming the missing role, since retrying an authorization failure only makes a clear error slow. One narrow extra case: the query endpoint intermittently returns a `404 GtmDimensionDataProvider...` for a subscription that plainly exists (observed live mid-build on a grouping that had worked minutes earlier); that specific signature is retried, a plain 404 is not.
  * Parsing is by **column name, never position** (`_column_index`), because the columnar response's order differs per query shape, and `UsageDate` arrives as the number `20260805` rather than a date string.

* **`apps/invoice-be/telemetry.py`** — `track_azure_cost_snapshot()` and `track_azure_cost_slice()`, plus `AZURE_COST_SNAPSHOT_EVENT_NAME` / `AZURE_COST_SLICE_EVENT_NAME`. Two event types because one row cannot carry a variable-length breakdown in a form KQL can chart. Absent values stay absent (a missing budget is not "0 spend"), and `collection_errors` rides on the snapshot event so a partial run reads as partial rather than as a quiet day. **Deviation worth recording:** the slice label field is `dimension_value`, not the obvious `name` — `name` is a reserved `LogRecord` attribute, so passing it through `extra=` makes `logging` raise inside an emitter that swallows exceptions by contract, i.e. the event silently never appears. The first test run caught exactly that.

* **`apps/invoice-be/scripts/sweep_azure_cost.py` (NEW)** — the scheduled entrypoint (`--dry-run`, `--json`, `--days`, `--no-forecast`), matching the existing `scripts/sweep_*.py` pattern. Chosen over an API endpoint because the Cost Management API is throttled and its data refreshes only a few times a day, and because the two intended consumers read differently: an Azure Workbook can only query Log Analytics/App Insights (it cannot call this app at all), while Feature 24's Ops Digest Agent runs inside this codebase and can call `collect_cost_snapshot()` directly in-process.
  * `configure_telemetry()` in that script calls `configure_azure_monitor(logger_name="invoice_be_telemetry")` itself, and `main()` force-flushes the logger provider before exit. Both are load-bearing, not boilerplate: `telemetry._emit_event()` only reaches `customEvents` if *this process* attached the exporter, and a job that exits seconds after emitting would otherwise drop the whole batch. (Note for whoever owns Feature 23: `scripts/run_agent_eval.py` does **not** do this, so its `track_eval_result()` events reach stdout/`ContainerAppConsoleLogs_CL` only, regardless of the connection string the job bicep passes it.)

* **`apps/invoice-be/config.py`** — `AZURE_SUBSCRIPTION_ID`, `AZURE_COST_RESOURCE_GROUP`, `AZURE_COST_BUDGET_NAME`, `AZURE_COST_ACCESS_TOKEN`, `AZURE_COST_CLI_FALLBACK`. All default empty/False; `cost_scope()` raises rather than guessing, because a wrong scope returns a valid-looking response for somebody else's spend.

* **`infra/modules/security/rbac-assignments.bicep`** — `costManagementRoleAssignment`, **Cost Management Reader** (`72fafb9e-0641-4937-9268-a91bfd8191a3`) at **resource-group** scope. Both the role ID and its sufficiency were verified live rather than assumed: the two operations this module calls register as `Microsoft.CostManagement/query/read` and `Microsoft.CostManagement/forecast/read` — `/read`, despite being HTTP POSTs — so they fall under that role's `Microsoft.CostManagement/*/read`, and the budget read under `Microsoft.Consumption/*/read`. RG scope is the narrowest that works; Cost Management has no per-resource scope to grant on. `az bicep build --file infra/07-rbac.bicep` compiles clean. **Not deployed** (Gap 294).

#### How this was verified — real API, real events

1. **The API shapes, before any code existed:** each request body was run through `az rest` against subscription `2ae37d8b-…` / `rg-invoice-llm-dev` and returned real rows. This is how the forecast endpoint's `MonthToDate` rejection and the numeric `UsageDate` were found rather than guessed.
2. **The module end-to-end against live Azure:** `python scripts/sweep_azure_cost.py --days 7 --no-forecast` (CLI-token path) returned 16,513.97 INR month-to-date, an 11-row `ServiceName` breakdown, a 12-row `ResourceType` breakdown and the live budget — and a mid-run transient 404 on the ResourceType call was caught by the partial-collection design, which is what prompted the narrow retry above.
3. **The telemetry actually landing in Application Insights:** the same run with the real connection string reported `Transmission succeeded: Item received: 20. Items accepted: 20`, and a follow-up query against `appi-invoicellm-dev` returns **1 `azure_cost_snapshot` + 19 `azure_cost_slice` rows** in `customEvents`, with all dimensions intact (`month_to_date_total`, `budget_percent_used`, `day_over_day_change_pct`, …). Aggregating the slices confirms the design intent: `summarize sum(amount) by dimension` gives `ServiceName → 16,513.97` and `ResourceType → 16,513.97`, i.e. each breakdown independently reconciles to the MTD total, and the `dimension` field is what stops a naive `sum()` double-counting the two views.

**Not verified:** the **managed-identity path has never authenticated**, because `id-invoicellm-dev` currently holds no Cost Management role (checked with `az role assignment list`) — every live call above used a CLI token from an already-privileged principal. The MI code path is exercised only by unit tests until Stage 7 is redeployed (Gap 294). The sweep is also **not scheduled** — no `Microsoft.App/jobs` resource exists for it yet — and no workbook panel consumes the events.

#### KQL the future Cost panel can use as-is

```kusto
// Spend trend + budget line
customEvents
| where name == "azure_cost_snapshot"
| extend d = customDimensions
| project timestamp,
          mtd = todouble(d.month_to_date_total),
          budget = todouble(d.budget_amount),
          forecast = todouble(d.budget_forecast_spend),
          currency = tostring(d.currency)
| render timechart

// Spend by service (pick one dimension -- the two views overlap by design)
customEvents
| where name == "azure_cost_slice"
| extend d = customDimensions
| where tostring(d.dimension) == "ServiceName"
| summarize amount = arg_max(timestamp, todouble(d.amount)) by service = tostring(d.dimension_value)
| render barchart
```

#### Findings, filed rather than silently fixed

* **The budget is denominated in INR, not USD, and is permanently breached (Gap 295).** `budget-invoicellm-dev` has `amount: 150` and the billing account bills in **INR**, so the live figures are `currentSpend 16,403.80` / `forecastSpend 24,601.01` — **10,935% used, 16,400% forecast**. Both notifications (80% actual, 100% forecasted) have therefore been in a permanently-fired state, which makes the one cost alert this project has worthless. `infra/10-budget.bicep`'s header comment says "USD" and the File Coordinates entry below still says "$300/mo"; the deployed param is 150. The module reports the currency on every dataclass and every event rather than assuming, so a panel built on it will not repeat the mistake.
* **Naming/RG drift between `params.dev.json` and what is deployed.** The live resource group is `rg-invoice-llm-dev` and the budget is `budget-invoicellm-dev` (prefix `invoicellm`), but `params.dev.json` sets `namingPrefix: "invoice-llm"`, which would derive `budget-invoice-llm-dev`. Deriving the name in code would 404 against the real environment, so `resolve_budget_name()` defaults to the deployed name and takes an override from settings.

---

### 2026-08-23 — Task 19.12: the combined Cost + Health/Performance Azure Workbook, built as one page (not tabs)

Closes out the plan from the first 2026-08-23 section above: one Azure Workbook covering both Area 1 (Cost) and Area 2 (Health/Performance), per the founder's explicit instruction to keep this as one combined dashboard rather than two, and to use Azure Workbooks despite this session's earlier real pain with them on Feature 23's AI Control Tower build (tab-rendering that silently fell back to a flat scroll, a `customWidth` unit that Workbooks silently ignores, a `tiles` visualization that clipped titles no matter how it was resized — full history in `be_features_tracker.md`'s narrative around the "single combined tabbed workbook was retired" entry and this doc's own citations of that history).

**Confirmed live before any JSON was written, not assumed:** Gap 295 is now fixed — `az consumption budget show --budget-name budget-invoicellm-dev` returns `amount: 20000.0` (INR) with `actual_50_percent`/`actual_75_percent`/`actual_95_percent` notifications, replacing the old permanently-breached ₹150 budget. The workbook's honesty panel states this, and separately flags that the one `azure_cost_snapshot` event that exists today was emitted by a sweep run that predates this fix, so its own `budget_amount`/percent-used fields still read the old ₹150 figure until `sweep_azure_cost.py` runs again.

#### What was built

* **`infra/monitoring/cost_health_workbook.json` (NEW)** — the workbook definition, 23 items, single scrolling page, no tabs, no `tiles` visualization, no `customWidth` tricks. Twelve data panels:
  * **Cost (Area 1):** spend trend + budget/forecast (one `timechart` plotting `month_to_date_spend`, `budget_amount`, `month_end_forecast` together — this single panel covers both "total spend trend" and "forecast vs. budget" from the original scope) and spend-by-service (`barchart`). Both reuse the exact KQL already verified live in this doc's Task 19.11 section, **adapted** from `customEvents`/`name`/`customDimensions` (the Application-Insights-classic aliases used when a workbook queries via `resourceType: microsoft.insights/components`) to `AppEvents`/`Name`/`parse_json(Properties)` (the native Log Analytics workspace table/column names) — because this workbook's `sourceId` is the raw `law-invoicellm-dev` workspace, not the App Insights component, matching `infra/modules/monitoring/dashboard.bicep`'s existing (never-deployed) convention. The adaptation was re-verified live, not assumed correct from the alias translation alone: both queries were run via `az monitor log-analytics query -w <law-workspace-id>` and returned the same 1 snapshot / 19 slice rows, same amounts, as the original `customEvents`-based query returned via `az monitor app-insights query`.
  * **Health (Area 2):** container status (`Replicas`/`CpuPercentage`/`MemoryPercentage` pivoted from `AzureMetrics`, 1h window — native Container Apps platform metrics, zero new instrumentation), container scale config (min/max replicas + provisioning state via Azure Resource Graph, since configured scale bounds are a resource property, not a metric), container restarts (`RestartCount` summed over 24h, also `AzureMetrics`), PostgreSQL status (`cpu_percent`/`memory_percent`/`storage_percent`/`active_connections`/`max_connections`/`is_db_alive`, 6h window) and Redis status (`serverLoad`/`usedmemorypercentage`/`connectedclients`/`cachehits`/`cachemisses`/`geoReplicationHealthy`, 6h window), and the dead-letter-queue panel (`ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"` — the identical query `alert-rules.bicep`'s Sev-1 DLQ alert already uses, per Gap 257).
  * **API performance by feature area:** the exact `case()`-over-`AppRequests.Name` KQL already verified live in the Gap 292 write-up above, unchanged except for one added filter (`AppRoleName != "invoice-be-local-f20-verify"`) so the panel does not present that write-up's own local verification rows as if they were real container traffic.
  * **Recent alerts:** the `alertsmanagementresources` Resource Graph query pattern recovered from the deleted `ai_control_tower.workbook.json`'s Health tab (`git show bd6a255^:Prod_Invoice_LLM/infra/monitoring/ai_control_tower.workbook.json` — the file itself is gone from the working tree, deleted in `bd6a255`, but still readable from git history), re-verified live against the real subscription rather than trusted from the old file: `az graph query` on the exact recovered KQL returned real day-binned alert counts by severity for the last 7 days.
  * **Two deliberate non-panels, stated as limitations rather than built against data that doesn't exist:** extraction quality (`services/extraction_quality_rollup.py`'s `field_correction_rollup()`/`alert_precision_rollup()` read Postgres `AuditLog` directly — a workbook's only data sources are Log Analytics/App Insights/Resource Graph/ARM/ADX, none of which is Postgres, and nothing mirrors this rollup's output into any of those the way `azure_cost.py`/`online_eval_signals.py` do for their own Postgres-backed data) and CI/CD gate status (the `verify-deployment` gate's pass/fail lives in the GitHub Actions run log, which a workbook cannot query at all). Both get a markdown-only panel explaining exactly why, rather than a KQL query that would either error or silently return nothing.

* **`infra/workbook-cost-health-only.bicep` (NEW)** — narrow, standalone deployment, following the same rationale as `gpt4o-deployment.bicep` and the deleted `agent-eval-job-only.bicep`: `params.dev.json`'s known stale image-tag drift makes a full `08-apps.bicep`/`09-monitoring.bicep` deploy risky, and this workbook only touches a `Microsoft.Insights/workbooks` resource neither stage otherwise creates for this purpose. `loadTextContent('./monitoring/cost_health_workbook.json')` recreates the `loadTextContent()` deploy pattern the (also deleted, never committed) `ai_control_tower_workbooks.bicep` used — that specific file no longer exists in the working tree or in git history (it was never committed; only the combined pre-split `ai_control_tower.workbook.json` was), so the pattern was rebuilt from the mechanism's description rather than copied from a file. References `law-invoicellm-dev` as `existing`, exactly as `09-monitoring.bicep`'s modules do. Does **not** touch or delete `infra/modules/monitoring/dashboard.bicep` (Task 19.5's 6-panel workbook, still wired into `09-monitoring.bicep` but never actually deployed) — retiring that module is a separate, deliberate cleanup left for a later pass, not a side effect of adding this one.

#### How this was verified — real Azure, every query, no invented properties

* **Every non-obvious Workbooks JSON property checked against the real schema before use**, not re-guessed from what "felt right" the way the earlier tab/`customWidth` bugs happened: downloaded the live `schema/workbook.json` from `microsoft/Application-Insights-Workbooks` and validated the finished file against it with `ajv` (Draft 2020-12-compatible) — **0 errors**. Separately cloned the full `microsoft/Application-Insights-Workbooks` repo (710 shipped `.workbook` files) to structurally cross-check the KQL-step (`type: 3`), parameter-step (`type: 9`, resource-picker `type: 6`), and Resource-Graph-step (`queryType: 1`, `resourceType: microsoft.resourcegraph/resources`, `crossComponentResources`) shapes actually used here against real shipped examples, rather than inventing property names — this is the same discipline the founder asked for given the earlier `"style": "tabs"` and `customWidth: "15%"` incidents.
* **Deliberately no tabs, no `tiles` visualization, no `customWidth` layout tuning anywhere in this file** — the three specific failure classes from the earlier build. Every panel is a full-width stacked item; the trade-off (more scrolling than a tabbed/tiled layout) was accepted explicitly rather than re-attempting a pattern that took multiple rounds to get right last time, for a build with no interactive-portal verification available to catch a repeat failure quickly.
* **Every KQL and ARG query in the file was executed live**, not just schema-checked, via `az monitor log-analytics query -w <law-invoicellm-dev workspace id>` and `az graph query` against the real `rg-invoice-llm-dev` subscription on 2026-08-23: cost trend/budget (1 row), spend-by-service (9 rows reconciling to the same MTD total Task 19.11 recorded), container status pivot (4 apps, real CPU/memory/replica values), container scale config via Resource Graph (5 apps, real min/max replica bounds matching `az resource list`), container restarts (0 rows = a confirmed real zero over 24h), Postgres status (6 metrics, real values), Redis status (6 metrics, real values), the DLQ query (0 rows over 7 days, confirmed real, same query the live Sev-1 alert uses), the API-performance-by-area `case()` grouping (executes correctly, returns the 4 verification-tagged rows before the `AppRoleName` filter and 0 after — confirming the filter works), and both Resource-Graph alert queries (real day-binned severity counts over the last 14 days, e.g. 3 Sev1 + 1 Sev2 on 2026-08-18).
* **`az bicep build --file infra/workbook-cost-health-only.bicep` compiles clean.**
* **`az deployment group what-if -g rg-invoice-llm-dev --template-file infra/workbook-cost-health-only.bicep` returned exactly one `Create` (the new workbook) and 49 `Ignore`** (every other resource already in the resource group, untouched) — confirming this deployment is as narrow as intended and will not modify or delete anything live. (Windows-specific note, not a defect in the deployment itself: the CLI's default console/pretty-print path threw `'charmap' codec can't encode character '₹'` trying to print the ₹ symbol embedded in the workbook's honesty-table text — the same class of cp1252-discards-Unicode issue Task 19.11 already documented for `az rest`. Worked around with `--no-pretty-print` redirected to a file, same as that section's workaround; the compiled ARM template on disk (checked directly, not through the CLI's print path) contains the ₹ and — characters correctly, confirming the deployment payload itself is unaffected — only the CLI's terminal rendering of the human-readable diff was.)

#### What was not verified, stated plainly

* **This deployment was not actually run.** `az deployment group create` was deliberately not executed — the what-if above is the full extent of live Azure verification for the deploy step itself. The workbook resource does not exist in Azure yet.
* **No disposable test workbook resource was created this time**, unlike the earlier tab-fix rounds' `PUT`/`GET` byte-round-trip against a real `Microsoft.Insights/workbooks` resource — that specific mutating call was blocked by this session's permission system as a state-changing Azure operation, and was not worked around. So unlike those earlier fixes, there is no live confirmation that Azure's own storage/round-trip of this exact payload is lossless; only the local schema validation and the what-if's `Create` diff are evidence that Azure will accept it.
* **No interactive Azure Portal access exists in this environment, at all.** How any panel actually lays out, whether the honesty-table markdown renders correctly, whether any grid column is unexpectedly narrow — none of this can be checked from here. Every claim above is about query correctness and the data those queries return, never about pixels. The founder (or whoever next has portal access) is the first person who will actually see this workbook rendered.

---

### 2026-08-24 — Ops-page field-by-field review: 4 manual workbook edits, and Gap 301's alert fix

The founder did a field-by-field review of the workbook above with the founder + architect. Two outcomes:

**Four edits made directly to `infra/monitoring/cost_health_workbook.json`:**
1. Removed the `extraction-quality-header` text panel outright — that content belongs to Feature 23's own (future) AI Eval & Observability workbook, not this one.
2. Removed the `cicd-header` text panel outright and permanently (not moved) — founder already gets CI/CD gate alerts directly from GitHub Actions, so this panel was a redundant view rather than a genuinely missing signal.
3. Edited the `header` panel's honesty table: removed the two rows for the panels above (formerly rows 10 and 11), added a dated "2026-08-24 update" note explaining both removals inline.
4. Replaced the `alerts-table` full detail-table panel (`alertsmanagementresources` row-per-alert query) with a single-value count query — `alertsmanagementresources | where type =~ "microsoft.alertsmanagement/alerts" | extend fired = todatetime(properties.essentials.startDateTime) | where fired > ago(24h) | summarize AlertsFired24h = count()` — retitled "Alerts fired, last 24h".

**Fifth edit, same day, follow-up to the field-by-field review:** `alerts-table`'s title originally carried the design rationale for the shrink inline (why a count instead of a full per-alert table). Trimmed to a plain title — **the workbook shows data only, no rationale/commentary text in a live tile** — with the reasoning relocated here: this panel was intentionally shrunk from a full detail table to a lightweight 24h count because a richer per-alert view (each alert's underlying condition, with recommendation text) belongs to the recommendation layer once that exists, not to Feature 20's data-only workbook. That layer is **Feature 24's Ops Digest Agent** (see `feature_23_ai_control_tower.md` and the F20/23/24 implementation status doc) — it reads `agent_eval_run` and `alertsmanagementresources` directly (not through any workbook) and produces the actual recommendation text on a 6h cadence. Revisit this panel once Feature 24 is deployed and confirmed to cover the same ground, at which point removing it entirely (rather than keeping a duplicate count) may make sense.

**Re-validated 2026-08-24, structural-only** (per this doc's own "How this was verified" discipline above — only the 4 edited regions were re-checked; the untouched KQL queries were not re-run):
- `JSON.parse`/PowerShell `ConvertFrom-Json` on the full file: valid, no syntax errors introduced by the manual edits.
- `az bicep build --file infra/workbook-cost-health-only.bicep`: compiles clean. (Note: `loadTextContent` embeds the JSON as an opaque string at compile time, so a clean bicep build alone does not itself prove the JSON is schema-valid — the checks below cover that.)
- Re-derived the original build's `ajv`-against-Microsoft's-live-schema check (this doc's own line 202 above): downloaded `microsoft/Application-Insights-Workbooks`'s current `schema/workbook.json` fresh and validated the full (edited) file against it with a freshly-installed `ajv` — **0 errors**. Did not re-clone the 710-shipped-template corpus this time — the edits removed two items and swapped one query/title, reusing item shapes (`type: 1` markdown, `type: 3` KQL/ARG step) already present and already cross-checked in the original build; no new shape was introduced that would need re-validating against real examples.
- Confirmed structurally: `extraction-quality-header` and `cicd-header` no longer appear anywhere in the file, as an item `name` or otherwise; `header`'s markdown contains the "2026-08-24 update" note; `alerts-table` now holds exactly the single `AlertsFired24h` count query with the expected title.

**Separately, Gap 301 (real bug, not a workbook edit)** — the CPU-high/memory-high alerts in `alert-rules.bicep` fired on threshold-plus-15-minute-window alone, with no check on whether autoscale (Gap 290) was already correctly handling the load and simply hadn't caught up yet within that window. **Fixed 2026-08-24, not yet deployed:**
- `modules/monitoring/alert-rules.bicep` — 5 new params (`backendMaxReplicas`/`workerMaxReplicas`/`frontendMaxReplicas`/`chromaDbMaxReplicas`/`websiteMaxReplicas`, defaults matching `08-apps.bicep`'s and `modules/data/chromadb.bicep`'s own maxReplicas defaults), threaded into the `containerApps` loop array as a `maxReplicas` field per app. Both `cpuAlerts` and `memoryAlerts` (`[for app in containerApps: ...]`) gained a second `AllOf` criterion: `{ name: 'ReplicasAtMax', metricName: 'Replicas', operator: 'GreaterThanOrEqual', threshold: app.maxReplicas, timeAggregation: 'Maximum' }` — so both required conditions (CPU/memory over threshold, AND replicas already at the app's configured ceiling) must hold before the alert fires.
- `09-monitoring.bicep` — declares the same 5 params and passes them into the `alertRules` module call, matching how `cpuAlertThreshold`/`memoryAlertThreshold`/etc. are already threaded through this stage.
- `az bicep build` clean on both files.
- `az deployment group what-if -g rg-invoice-llm-dev --template-file 09-monitoring.bicep` (parameters filtered to this stage's declared params, mirroring `deploy-all.ps1`'s own `New-StageParamArgs` logic) returned `Succeeded`: 22 Modify / 22 Create / 31 Ignore (75 total). All 10 CPU/memory alerts (backend, worker, frontend, website, chromadb) show `Modify` with a `properties.criteria.allOf` delta adding the new `ReplicasAtMax` criterion — verified directly on `alert-ca-invoice-be-dev-cpu-high`: `threshold: 5` (matching `backendMaxReplicas`'s default), `operator: GreaterThanOrEqual`, `timeAggregation: Maximum`. The same 10 resources also show unrelated pre-existing drift (`properties.actions` action-group id, `properties.windowSize` PT5M→PT15M) from this session's earlier dual-action-group/90%-threshold/PT15M-window edits — those predate this fix and are not caused by it; the live dev alerts simply haven't been redeployed since those changes landed.
- **Not deployed** — `az deployment group create` was deliberately not run. The founder will decide when to apply this to live Azure.

### 2026-08-24 (later same day) — Tile redesign, real status coloring, spacing cleanup — deployed and verified live

Founder-driven follow-up to the field-by-field review above. Three rounds, each deployed and re-verified against the live `serializedData` (not just deploy status) via `az rest ... canFetchContent=true`.

**Round 1 — charts to tiles.** All remaining chart/table panels (spend trend, spend-by-service, container status, scale config, PostgreSQL, Redis, API perf by area, alerts trend) converted to `visualization: "tiles"`. Old workbook resource (`a7c1e9d4-...`) deleted and recreated fresh as `618c81c7-353d-498a-93be-becc2e3e84cf` (bicep's `workbookId` default updated to match) after a Portal caching concern turned out to need a genuinely new resource ID to rule out.

**Round 2 — header removed, first-pass status coloring.** Main header/honesty-table panel deleted outright per founder instruction. `formatter: 8` (Thresholds) coloring added: ≥90 red / ≥70 yellow / else green on percent metrics, blue as the explicit default for metrics with no status meaning (cost, request counts).

**Round 3 — coloring audit found 3 real defects, all fixed:**
1. **`is_db_alive`/`geoReplicationHealthy` showed green when down/unhealthy** — both were sharing one threshold column with unrelated percent metrics, and `0` fell under the `<70` "green" bucket regardless of what it meant. Fixed by splitting each into its own dedicated tile (`db-status-postgres-liveness`, `db-status-redis-liveness`) with clean text-equality coloring (`"Alive"`/`"Down"`, `"Healthy"`/`"Unhealthy"`).
2. **API perf's Error rate never colored** — was merged into the same blue-only tile as Requests/P95 latency. Split into its own tile (`api-perf-error-rate`), ≥10% red / ≥5% yellow / else green.
3. **Budget overage never colored** — spend/forecast tiles showed the raw $ figure with no threshold. Reworked so the tile's colored `Value` is % of budget consumed (≥100% red / ≥80% yellow / else green), with the real $ amount moved to the `Detail` subtitle.

**Also addressed, same pass, not defects but flagged as "coincidentally correct, not meaningfully evaluated":** Container Replicas count, DB connection counts (`active_connections`/`max_connections`), and Redis cache counts (`connectedclients`/`cachehits`/`cachemisses`) were all sharing the percent-style threshold rule purely by luck (small numbers never crossing 70/90). Split into their own blue (no-status) tiles, and two new **derived, genuinely meaningful** tiles added: PostgreSQL connection utilization % (`active/max`, red/yellow/green) and Redis cache hit ratio % (`hits/(hits+misses)`, inverted scale — low is bad).

**Alerts fired, last 24h** (`alerts-table`) also converted to a colored tile (0=green, ≥5=red, else yellow) — previously the only remaining un-colored, un-tiled panel besides restarts/DLQ.

**Spacing cleanup**, same deploy: removed 3 purely-redundant `### Section` text panels whose content the tile titles already stated (`container-status-header`, `db-status-header`, `dlq-header`); shortened the Cost, API-perf, Alerts, and footer text panels from multi-sentence prose to one-liners. Net panel count went from 20 → 25 (the coloring-correctness splits added more panels than the spacing pass removed), but total page text dropped substantially. **Tabs were explicitly considered and rejected** for this — Feature 23's own build history in this repo hit multiple rounds of real Workbooks tab bugs, and this environment has no portal access to catch a repeat quickly; reducing prose/redundant headers was judged the lower-risk lever.

**Verified live, all 3 rounds**: `az bicep build` clean each time; each deploy's `properties.serializedData` pulled back via direct REST call (not just `provisioningState`) and checked for the expected `tiles`/`thresholdsGrid` content, absence of the old header, and — after the round-3 fix — absence of a broken placeholder threshold rule caught and corrected before that deploy. Final state: 25 items, 0 leftover chart/table visualizations except the 2 panels never in scope (`container-restarts`, `dlq-panel`) and the always-empty API-perf tiles pending Gap 292's instrumentation deploy.

---

### File Coordinates

* **Compute & Container Lifecycle (IaC):**
  * `infra/08-apps.bicep` → passes `APPLICATIONINSIGHTS_CONNECTION_STRING` to all 4 container app modules.
  * `infra/modules/compute/invoice-be.bicep` → Liveness probe (`GET /health`), Readiness probe (`GET /health/readiness`), Startup probe (30s initial delay), AppInsights connection string env var.
  * `infra/modules/compute/queue-worker.bicep` → AppInsights connection string env var, Dead-Letter Queue binding on `extraction-tasks-deadletter-queue`.
  * `infra/modules/compute/invoice-fe.bicep` → AppInsights connection string env var, TCP/HTTP Liveness and Readiness probes on port 3000.
  * `infra/modules/compute/invoice-website.bicep` → AppInsights connection string env var, Liveness and Readiness probes on port 3000.

* **Monitoring, Visual Dashboards & Alerting (IaC):**
  * `infra/09-monitoring.bicep` → wires `ca-invoice-website` into diagnostic settings and metric alerts; deploys the unified Azure Workbook dashboard module.
  * `infra/modules/monitoring/dashboard.bicep` (**NEW**) → `Microsoft.Insights/workbooks` resource with 6 visual panels (Container Health, Queue Throughput & DLQ, Latency Heatmap, AI TPM Quotas, Database & Redis Pool, Error Incident Feed).
  * `infra/modules/monitoring/alert-rules.bicep` → Sev 1 DLQ poison alert is a **log-based** `scheduledQueryRules` query (`ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"`) — **BE Gap 257**, replacing a `QueueMessageCount`/`QueueName` metric filter Azure Storage does not expose. Also `ca-invoice-website` 5xx error alert. **Gap 301 (fixed 2026-08-24, not deployed):** `cpuAlerts`/`memoryAlerts` now require a second `AllOf` criterion (`Replicas >= app.maxReplicas`, via new `backendMaxReplicas`/`workerMaxReplicas`/`frontendMaxReplicas`/`chromaDbMaxReplicas`/`websiteMaxReplicas` params) so they only fire once autoscale (Gap 290) is genuinely maxed out — see the 2026-08-24 section above.
  * `infra/modules/monitoring/action-group.bicep` → adds Webhook receivers for Microsoft Teams / Slack incident channels and PagerDuty integration alongside email receivers.
  * `infra/10-budget.bicep` → Azure Monthly Spending Budget with 50%/75%/95%-actual spend alerts. **Correction (2026-08-23):** the "$300/mo cap" this line used to claim was wrong twice over — it was really `monthlyBudgetAmount: 150` in a billing account that bills in **INR** (Gap 295). **Fixed live the same day**: `az consumption budget show --budget-name budget-invoicellm-dev` now returns `amount: 20000.0` INR with `actual_50_percent`/`actual_75_percent`/`actual_95_percent` notification thresholds, replacing the old permanently-breached ₹150/80%/100% configuration.
  * `infra/modules/security/rbac-assignments.bicep` → `costManagementRoleAssignment`: **Cost Management Reader** (`72fafb9e-0641-4937-9268-a91bfd8191a3`) granted to the user-assigned identity at **resource-group** scope, so `services/azure_cost.py` can call `Microsoft.CostManagement/query|forecast` and read the budget. The only RG-scoped assignment in that file — Cost Management has no per-resource scope. **Not deployed yet (Gap 294).**

* **Backend Telemetry & Structured Logging:**
  * `apps/invoice-be/main.py` → initializes `azure-monitor-opentelemetry` APM via `configure_azure_monitor()`, recording success in the module-level `azure_monitor_configured` flag; calls `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")` after the app + middleware are built, which is what actually populates App Insights' `AppRequests` (Task 19.10 / Gap 292); defines `read_root`, `health`, `health_liveness` and `health_readiness` (PostgreSQL connection check + Redis ping); registers `TracingAndLoggingMiddleware` and `CORSMiddleware`.
  * `apps/invoice-be/utils/logging_config.py` → `StructuredJsonFormatter`, `setup_structured_logging`, and `TracingAndLoggingMiddleware.dispatch`, which reads `opentelemetry.trace.get_current_span()` to stamp `trace_id` onto every JSON access log. That read only resolves to a real OTel trace id now that Task 19.10 puts a server span in scope; before it, it always fell through to the `request_id` uuid4 fallback, so console logs could never be joined to App Insights telemetry.
  * `apps/invoice-be/queue_worker/main_worker.py` → OpenTelemetry tracer initialization; implements Dead-Letter Queue (DLQ) routing on message retry count $\ge 5$; structured JSON log formatting with `tenant_id`, `file_id`, and `trace_id`.
  * `apps/invoice-be/routers/billing.py` → telemetry logging for PayU checkout completions, hash mismatches, payment failures, and tenant quota thresholds (80%/100%).

* **Azure Cost Visibility (Area 1, Task 19.11):**
  * `apps/invoice-be/services/azure_cost.py` (**NEW**) → `cost_scope`, `is_configured`, `resolve_budget_name`, `_acquire_token`/`_fetch_managed_identity_token`/`_fetch_cli_token`/`reset_token_cache`, `_request_with_retry`, `_column_index`/`_parse_usage_date`/`_parse_daily_rows`/`_parse_grouped_rows`, `get_month_to_date_daily_spend`, `get_daily_spend`, `get_spend_by_dimension`, `get_month_end_forecast`, `get_budget_status`, `collect_cost_snapshot`, `emit_cost_snapshot_telemetry`; dataclasses `DailySpend`, `SpendSlice`, `BudgetStatus`, `MonthEndForecast`, `CostSnapshot`; exceptions `AzureCostError`/`CostConfigurationError`/`CostAuthError`/`CostApiError`.
  * `apps/invoice-be/telemetry.py` → `track_azure_cost_snapshot`, `track_azure_cost_slice`, `AZURE_COST_SNAPSHOT_EVENT_NAME` (`azure_cost_snapshot`), `AZURE_COST_SLICE_EVENT_NAME` (`azure_cost_slice`).
  * `apps/invoice-be/scripts/sweep_azure_cost.py` (**NEW**) → `configure_telemetry`, `_print_human`, `main`. The scheduled entrypoint; attaches the Azure Monitor exporter itself and force-flushes before exit.
  * `apps/invoice-be/config.py` → `AZURE_SUBSCRIPTION_ID`, `AZURE_COST_RESOURCE_GROUP`, `AZURE_COST_BUDGET_NAME`, `AZURE_COST_ACCESS_TOKEN`, `AZURE_COST_CLI_FALLBACK`.
  * `apps/invoice-be/tests/test_azure_cost.py` (**NEW**) → 40 tests over parsing, auth chain, retry/throttling, request shapes, budget, snapshot partial-failure and telemetry emission.

* **Cost + Health/Performance Workbook (Area 1 + Area 2 combined, Task 19.12):**
  * `infra/monitoring/cost_health_workbook.json` (**NEW**) → single-page Azure Workbook definition, 23 items, no tabs. Cost panels (spend trend + budget/forecast, spend by service), Health panels (container status/scale-config/restarts, Postgres status, Redis status, DLQ), API performance by feature area, and markdown-only limitation panels for Extraction Quality and CI/CD gate status (neither is queryable from a workbook — see the dated section above). Schema-validated against Microsoft's live `schema/workbook.json` (0 errors); every KQL/ARG query run live against `law-invoicellm-dev` before being written here.
  * `infra/workbook-cost-health-only.bicep` (**NEW**) → narrow standalone deploy, `loadTextContent('./monitoring/cost_health_workbook.json')`, references `law-invoicellm-dev` as `existing`. Not routed through `08-apps.bicep`/`09-monitoring.bicep`, matching `gpt4o-deployment.bicep`'s rationale. `az bicep build` clean; `what-if` returns exactly one `Create`. **Not deployed** — `az deployment group create` was deliberately not run.

* **Frontend Telemetry & CI/CD Verification:**
  * `apps/invoice-fe/app/layout.tsx` → initializes `@microsoft/applicationinsights-web` for Real User Monitoring (RUM), capturing client-side JavaScript crashes and React hydration errors.
  * `.github/workflows/deploy-prod.yml` → adds post-deployment synthetic health check step verifying `GET /health` on all 4 deployed container apps before completing deployment.

---

### Functionality (Target Design)

#### 1. Container Lifecycle & Self-Healing Probes
Eliminates zombie/hung container instances. When a container process is deadlocked or its database connection pool is starved:
* **Liveness Probe:** Periodically checks `/health`. If unresponsive for 3 consecutive intervals (30s), Azure Container Apps terminates the container replica and starts a fresh instance.
* **Readiness Probe:** Checks `/health/readiness` (DB ping). If database pool headroom $<5\%$, the probe returns `503 Unavailable`, causing ACA to stop routing incoming user traffic to that replica until it recovers.
* **Startup Probe:** Gives container up to 60s during cold boot to load Python dependencies before liveness probes begin polling.

#### 2. OpenTelemetry APM & End-to-End Distributed Tracing
Instruments FastAPI, SQLAlchemy, Redis, and HTTPX. Injects a continuous `trace_id` that correlates:
$$\text{Browser} \longrightarrow \text{Website Gateway} \longrightarrow \text{Frontend} \longrightarrow \text{Backend API} \longrightarrow \text{PostgreSQL / Redis / Azure OpenAI}$$
Generates a visual **Application Map** in Azure Portal showing real-time call volumes, latencies, and red-node failure highlights.

#### 3. Structured JSON Logging with Trace & Tenant ID Correlation
Standardizes all application logs into structured JSON:
```json
{
  "timestamp": "2026-08-17T10:02:14.123Z",
  "level": "ERROR",
  "service": "queue-worker",
  "tenant_id": "tenant_acme_corp",
  "file_id": "inv_9921_corrupted.pdf",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "error_type": "DocIntelCorruptedPDFError",
  "retry_count": 5,
  "action": "moved_to_deadletter_queue"
}
```

#### 4. Dead-Letter Queue (DLQ) & Poison Message Isolation
When a corrupted or password-protected PDF causes `ca-queue-worker-prod` to fail processing $\ge 5$ times:
* The message is routed to `extraction-tasks-deadletter-queue` with diagnostic metadata.
* The corrupted message is deleted from the main queue, allowing remaining valid invoices to process without stalling.
* An immediate Sev 1 alert is emitted.

#### 5. Azure Workbooks Operations Dashboard
A single-pane-of-glass visual dashboard deployed via IaC featuring:
1. Container Health & Active Replica Matrix.
2. Storage Queue Ingestion & DLQ Live Throughput.
3. API Latency Heatmap (P50/P95/P99) & 5xx Error Rates.
4. Azure OpenAI (500k TPM quota) and Document Intelligence Concurrency Burn.
5. PostgreSQL Connection Pool Usage & Redis Cache Hit Ratio.
6. Error Breakdown and Alert Incident Feed by Tenant.

#### 6. Multi-Channel Alerting & Warnings
* **Payment Alerts:** PayU checkout failure, hash tampering, and subscription expiration reminders.
* **Tenant Quota Warnings:** In-app yellow warning banner at 80% quota (40/50 free invoices) and red lock banner at 100% (402 Payment Required).
* **Cloud Budget Alerts:** $300/month Azure spending budget alert at 80% actual spend and 100% forecasted spend.
* **AI Quota Warnings:** Sev 2 alert on Azure OpenAI 429 throttling (>5 client errors in 5m).
* **Delivery Channels:** Slack / Microsoft Teams webhook channels (`#alerts-billing`, `#alerts-infra`), PagerDuty on-call, and Action Group emails.

#### 7. Client-Side Real User Monitoring (RUM)
Captures uncaught React exceptions, client-side route transitions, and Core Web Vitals (LCP, FID) in `invoice-fe` and `invoice-website`.

#### 8. CI/CD Post-Deployment Verification Gate
Adds automated health checks in `deploy-prod.yml` to verify `GET /health` across all container apps immediately after `az containerapp update`.

---

### Tasks

- [x] **Task 19.1: Container Health Probes & AppInsights Injection in Bicep** — Updated `06-compute-env.bicep`, `invoice-be.bicep`, `queue-worker.bicep`, `invoice-fe.bicep`, `invoice-website.bicep`, and `08-apps.bicep` to add Liveness, Readiness, and Startup probes and pass `APPLICATIONINSIGHTS_CONNECTION_STRING`.
- [x] **Task 19.2: OpenTelemetry APM & Health Endpoints in Backend** — Configured `azure-monitor-opentelemetry` in `apps/invoice-be/main.py`; implemented `/health`, `/health/liveness`, and `/health/readiness` (DB ping + Redis check). Added `azure-monitor-opentelemetry` to `pyproject.toml`.
- [x] **Task 19.3: Structured JSON Logging Middleware** — Created `apps/invoice-be/utils/logging_config.py` with `StructuredJsonFormatter` and `TracingAndLoggingMiddleware`; wired into `main.py` and `main_worker.py` to emit JSON logs with `trace_id`, `request_id`, and `tenant_id`.
- [x] **Task 19.4: Dead-Letter Queue (DLQ) Isolation in Queue Worker** — Updated `apps/invoice-be/queue_worker/main_worker.py` to route messages failing $\ge 5$ attempts to `extraction-tasks-deadletter-queue` and purge them from the primary queue.
- [x] **Task 19.5: Azure Workbooks Operations Dashboard Bicep Module** — Created `infra/modules/monitoring/dashboard.bicep` defining the 6-panel single-pane-of-glass workbook; wired into `09-monitoring.bicep`.
- [x] **Task 19.6: Website Diagnostics & DLQ Alert Rules** — Added `ca-invoice-website` to diagnostic settings and 5xx alerts in `09-monitoring.bicep` and `alert-rules.bicep`; added Sev 1 Dead-Letter Queue (DLQ) poison message alert. **Corrected 2026-08-19 (BE Gap 257):** the original rule was a `metricAlerts` filter on `QueueMessageCount` + `QueueName` — that dimension does not exist on Azure Storage queue metrics, so the alert could never fire. Replaced with `Microsoft.Insights/scheduledQueryRules` over `ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"` (same KQL as the workbook DLQ panel). `az bicep build --file infra/09-monitoring.bicep` compiles clean. **Not yet deployed / poison-message fire-tested on Azure.**
- [x] **Task 19.8: Client-Side Real User Monitoring (RUM)** — Added `@microsoft/applicationinsights-web` to `package.json` and created `AppInsightsProvider.tsx` wrapping `RootLayout` in `apps/invoice-fe/app/layout.tsx`.
- [x] **Task 19.9: CI/CD Post-Deployment Verification Gate** — Added `verify-deployment` job in `.github/workflows/deploy-prod.yml` to automatically verify public ingress and container app `Succeeded` provisioning state after release. **Extended 2026-08-19 (BE Gap 258):** dev now has the same gate in `deploy-dev.yml` (website ingress + backend `/health/readiness` curl + all four dev apps' traffic-bearing revision `Healthy`/`Running`), and `_deploy-service.yml` polls each service's latest revision health immediately after `az containerapp update` (dev and prod deploy jobs).

- [x] **Task 19.10: Fix empty `AppRequests` — real HTTP request telemetry (2026-08-23, Gap 292)** — `AppRequests` had **0 rows over 90 days** for every route despite `APPLICATIONINSIGHTS_CONNECTION_STRING` being live on `ca-invoice-be-dev`. The cause was **not** missing instrumentation or missing config — Task 19.2's `configure_azure_monitor()` call was already correct, and `opentelemetry-instrumentation-fastapi` ships as a hard `Requires-Dist` of `azure-monitor-opentelemetry` (pinned `>=0.64b0,<0.65.0`, present in `uv.lock`), so **no dependency change was needed**. The cause was a Python import-order trap, detailed in the narrative section above. **Implemented in `main.py`:** `configure_azure_monitor()` now sets `azure_monitor_configured = True` on success, and a new block after the middleware registration calls `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")` guarded by that flag and wrapped in the same warn-don't-crash `try/except` as the distro init. Chose `instrument_app()` over reordering the import deliberately: it binds to this specific app instance rather than depending on statement order, so a future edit that moves the `from fastapi import FastAPI` line cannot silently re-break telemetry. **Verified live** — 0 → 4 real `AppRequests` rows in `appi-invoicellm-dev` with templated route names, 200/500/401 result codes and real durations, 0 `/health` rows; plus 8/8 feature-area routes emitting SERVER spans locally. Full evidence in the 2026-08-23 narrative section. **Not deployed** — `ca-invoice-be-dev` runs the pre-fix image, so live container `AppRequests` stay 0 until a deploy.

- [x] **Task 19.11: Area 1 — real Azure spend from the Cost Management API (2026-08-23, Gaps 294/295)** — the application had zero visibility of actual Azure infrastructure spend; the only cost telemetry that existed (`llm_agent_call`) covers LLM tokens, measured this day at **2.8% of the bill**. Built `services/azure_cost.py` (Cost Management `query` + `forecast`, Consumption `budgets`, managed-identity/CLI token chain, 429-aware retry, `collect_cost_snapshot()`), `telemetry.track_azure_cost_snapshot`/`track_azure_cost_slice`, `scripts/sweep_azure_cost.py`, five `config.py` settings, and the `Cost Management Reader` RG-scope role assignment in `infra/modules/security/rbac-assignments.bicep`. Written **after** every request shape was confirmed with `az rest` against the live subscription, which is how the forecast endpoint's `MonthToDate` rejection and the numeric `UsageDate` were found rather than guessed. **Verified live end-to-end:** the sweep returned real spend (16,513.97 INR MTD, 11 services, 12 resource types, the live budget) and the resulting events are queryable in `appi-invoicellm-dev` — 1 `azure_cost_snapshot` + 19 `azure_cost_slice` rows, each breakdown independently reconciling to the MTD total. 40 new tests in `tests/test_azure_cost.py`; `az bicep build --file infra/07-rbac.bicep` clean. **Deviations from the original plan, stated rather than buried:** (1) implemented on `httpx` against the REST API instead of the `azure-mgmt-costmanagement`/`azure-identity` SDKs — no managed-identity Python code existed in this repo at all, and two SDKs plus a lockfile regeneration for three HTTP calls was not worth it; `_fetch_managed_identity_token()` is the seam to swap later. (2) Scheduled emission rather than an API endpoint (reasons in the narrative section). (3) "Cost per invoice processed" and "idle resource detection" from the Area 1 plan are **not** built — the first needs a Postgres join no workbook can do, the second needs Area 2's metrics. **Not verified:** the managed-identity path has never authenticated (the identity holds no cost role until Stage 7 is redeployed — Gap 294), the sweep is not scheduled as a `Microsoft.App/jobs` resource, and no workbook panel consumes the events yet.

- [x] **Task 19.12: the combined Cost + Health/Performance Azure Workbook, built as one page (2026-08-23)** — closes the "no workbook panel consumes the events yet" gap Task 19.11 left open, and delivers Area 2's health/performance panels alongside it in the same file, per the founder's explicit "one combined workbook" instruction. Built `infra/monitoring/cost_health_workbook.json` (12 data panels + 2 markdown-only limitation panels, single scrolling page, no tabs) and `infra/workbook-cost-health-only.bicep` (narrow standalone deploy). Full build/verification record in the dated section above. **Deliberately excludes tabs, `tiles` visualization and `customWidth` layout tuning** — the three specific failure classes this session's earlier AI Control Tower workbook build hit and took multiple rounds to fix; every property actually used was checked against Microsoft's live `schema/workbook.json` (`ajv`, 0 errors) and cross-referenced against real shipped templates from a full clone of `microsoft/Application-Insights-Workbooks` (710 files) rather than re-guessed. **Verified live:** every KQL/ARG query executed against the real `law-invoicellm-dev` workspace and subscription via `az monitor log-analytics query`/`az graph query`, including confirming Gap 295's budget fix is live (20,000 INR, 50/75/95% thresholds) and that the cost-event KQL needed adapting from `customEvents`/`name`/`customDimensions` (App-Insights-classic aliases) to `AppEvents`/`Name`/`parse_json(Properties)` (native Log Analytics column names) to work against this workbook's `sourceId`, which is the raw workspace, not the App Insights component. `az bicep build` clean; `az deployment group what-if` returns exactly one `Create`, zero unexpected changes. **Not verified:** the deployment itself was not run (`az deployment group create` was deliberately not executed), no disposable test workbook resource was created this time (that `PUT` was blocked by the session's permission system as a mutating Azure operation, and the block was not worked around), and there is no interactive Azure Portal access in this environment at all — every claim above is about query correctness and returned data, never about how any panel actually renders.

---

### Verification Plan

#### Automated Tests
```powershell
# 1. Validate Bicep syntax and compilation across all modified modules
az bicep build --file Prod_Invoice_LLM/infra/08-apps.bicep
az bicep build --file Prod_Invoice_LLM/infra/09-monitoring.bicep
az bicep build --file Prod_Invoice_LLM/infra/07-rbac.bicep   # Task 19.11 role assignment
az bicep build --file Prod_Invoice_LLM/infra/workbook-cost-health-only.bicep   # Task 19.12 workbook

# 2. Run backend test suite
cd Prod_Invoice_LLM/apps/invoice-be
pytest -v tests/

# 3. Area 1 cost module only (Task 19.11) -- no Azure credential needed
pytest -v tests/test_azure_cost.py
```

#### Manual & Staging Verification
1. **Health Probes Verification:** Run `az containerapp show --name ca-invoice-be-dev -g invoice-llm-dev` and verify probes are populated and active.
2. **Telemetry Ingestion Check:** Execute API calls and verify distributed traces appear in Application Insights `AppRequests` and Application Map.
3. **Dead-Letter Queue Isolation Test:** Inject malformed payload into `extraction-tasks-queue` and verify it routes to `extraction-tasks-deadletter-queue` without worker crash.
4. **Dashboard Verification (Task 19.5's old 6-panel workbook — still not deployed, superseded by Task 19.12 for Areas 1/2):** Open Azure Portal $\rightarrow$ Monitor $\rightarrow$ Workbooks $\rightarrow$ *Invoice AI Operations Hub* and verify all 6 panels render live data.
5. **Azure Cost Collection (Task 19.11):** with `AZURE_SUBSCRIPTION_ID`/`AZURE_COST_RESOURCE_GROUP` set and a credential available, run `python scripts/sweep_azure_cost.py --dry-run` and confirm real spend, a service breakdown and the live budget come back; then run it without `--dry-run` (with `APPLICATIONINSIGHTS_CONNECTION_STRING` set) and confirm `customEvents | where name startswith "azure_cost"` returns rows in `appi-invoicellm-dev`. Done 2026-08-23 via the CLI-token path.
6. **Managed-identity cost access (Task 19.11, still outstanding — Gap 294):** after redeploying Stage 7, confirm `az role assignment list --assignee <id-invoicellm-dev principalId>` shows `Cost Management Reader` at the resource group, then run the sweep **inside** a container/job (no CLI available there) and confirm it authenticates through `IDENTITY_ENDPOINT` rather than raising `CostAuthError`.
7. **Cost + Health/Performance Workbook (Task 19.12, still outstanding):** run `az deployment group create -g rg-invoice-llm-dev -f Prod_Invoice_LLM/infra/workbook-cost-health-only.bicep` (not yet run — only `what-if` has been), then open the resulting workbook in Azure Portal $\rightarrow$ Monitor $\rightarrow$ Workbooks and confirm all 12 data panels render (not just execute via CLI) and that the two markdown-only limitation panels (Extraction Quality, CI/CD gate status) read clearly. This is the first real portal-rendering check this workbook will get — none was possible from this environment.
