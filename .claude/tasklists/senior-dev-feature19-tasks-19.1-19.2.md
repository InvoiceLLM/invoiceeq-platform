# Feature 19 (Tasks 19.1 & 19.2) — Container Health Probes & OpenTelemetry APM

- [x] Task 19.1: Update `infra/modules/compute/invoice-be.bicep` with Liveness, Readiness, Startup probes + `APPLICATIONINSIGHTS_CONNECTION_STRING`
- [x] Task 19.1: Update `infra/modules/compute/queue-worker.bicep` with `APPLICATIONINSIGHTS_CONNECTION_STRING`
- [x] Task 19.1: Update `infra/modules/compute/invoice-fe.bicep` and `invoice-website.bicep` with Probes + `APPLICATIONINSIGHTS_CONNECTION_STRING`
- [x] Task 19.1: Update `infra/06-compute-env.bicep`, `infra/08-apps.bicep`, `infra/09-monitoring.bicep` to provision AppInsights and thread `appInsightsConnectionString` to all 4 container apps
- [x] Task 19.2: Added `azure-monitor-opentelemetry>=1.6.0` to `apps/invoice-be/pyproject.toml`
- [x] Task 19.2: Update `apps/invoice-be/main.py` with OpenTelemetry APM initialization + `/health`, `/health/liveness`, and `/health/readiness` (PostgreSQL DB ping + Redis checks)
- [x] Verification: Validated Bicep builds (`az bicep build`) across all modified infra modules (`06-compute-env.bicep`, `08-apps.bicep`, `09-monitoring.bicep`) with exit code 0; verified Python syntax of `main.py`.
- [x] Documentation: Updated `feature_19_observability_monitoring_alerts.md` with completed task progress.

Status: Tasks 19.1 and 19.2 complete.
