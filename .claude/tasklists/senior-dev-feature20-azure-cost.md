# senior-dev — Feature 20 Area 1: real Azure cost visibility

Scope: a backend service that queries the Azure Cost Management API for real infrastructure
spend (daily/MTD, by service, by resource type, forecast vs. budget), emitted as telemetry so
a workbook panel and the planned Ops Digest Agent (Feature 24) can both read it.

- [x] Read `.claude/CONVENTIONS.md`, `feature_20_observability_monitoring_alerts.md` (2026-08-23 section), tracker
- [x] Read existing patterns: `services/storage.py`, `telemetry.py`, `services/online_eval_signals.py`, `scripts/sweep_*.py`, `infra/10-budget.bicep`, `infra/07-rbac.bicep`, `modules/security/rbac-assignments.bicep`, `modules/compute/scheduled-job.bicep`, `config.py`
- [x] Confirm what auth exists today: **no `azure.identity` anywhere in the repo**, no `azure-mgmt-costmanagement`; `httpx` is already a dependency; ACA jobs already get `AZURE_CLIENT_ID`
- [x] Verify the real API live with `az rest` before writing any code:
  - [x] `POST {rgScope}/providers/Microsoft.CostManagement/query?api-version=2023-03-01`, Daily/MonthToDate → real rows (INR)
  - [x] same, grouped by `ServiceName` → 11 services
  - [x] same, grouped by `ResourceType` → 12 resource types
  - [x] `POST .../forecast?api-version=2023-03-01` — `MonthToDate` is REJECTED, `Custom` + explicit `timePeriod` works
  - [x] `GET {rgScope}/providers/Microsoft.Consumption/budgets/budget-invoicellm-dev?api-version=2023-11-01` → amount / currentSpend / forecastSpend
  - [x] Live RG is `rg-invoice-llm-dev` and budget is `budget-invoicellm-dev` (params.dev.json's `namingPrefix` would produce different names — drift, recorded)
- [x] Verify RBAC facts live: `Cost Management Reader` = `72fafb9e-...`, ops are `Microsoft.CostManagement/query/read` + `/forecast/read` (covered by `Microsoft.CostManagement/*/read`); identity `id-invoicellm-dev` currently has **no** cost role
- [x] `services/azure_cost.py` — token chain, retry/429 handling, query/forecast/budget calls, `collect_cost_snapshot()`
- [x] `telemetry.py` — `track_azure_cost_snapshot()` / `track_azure_cost_slice()`
- [x] `config.py` — `AZURE_SUBSCRIPTION_ID`, `AZURE_COST_RESOURCE_GROUP`, `AZURE_COST_BUDGET_NAME`, `AZURE_COST_ACCESS_TOKEN`, `AZURE_COST_CLI_FALLBACK`
- [x] `scripts/sweep_azure_cost.py` — the scheduled entrypoint
- [x] `tests/test_azure_cost.py` — real tests over parsing/auth/retry/snapshot/telemetry
- [x] Run the module against the **real** Cost Management API (CLI-token path) and record the output
- [x] `infra/modules/security/rbac-assignments.bicep` — Cost Management Reader at RG scope (role ID verified live), `az bicep build` clean
- [x] Update `feature_20_observability_monitoring_alerts.md` (named files/functions + deviations)
- [x] Update `be_features_tracker.md` (dated entry + Gap 292 for the un-deployed role assignment)

Final status: complete. Module verified against the live Cost Management API via the CLI-token
path (real INR spend returned); the managed-identity path is code-complete but cannot be
verified until the new `Cost Management Reader` assignment is deployed — filed as Gap 292.
