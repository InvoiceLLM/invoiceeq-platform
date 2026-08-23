# senior-dev — Feature 20: fix empty `AppRequests` (HTTP request telemetry)

- [x] Read CONVENTIONS, feature_20 spec 2026-08-23 section, tracker
- [x] Inspect `main.py`, `pyproject.toml`, `utils/logging_config.py`, installed OTel packages
      → `azure-monitor-opentelemetry` 1.8.9 + `opentelemetry-instrumentation-fastapi` 0.64b0 both present;
        `configure_azure_monitor()` already called. So this was path 2, not path 1.
- [x] Determine root cause — **import-order trap**: `FastAPIInstrumentor._instrument()` rebinds
      `fastapi.FastAPI`; `main.py:6` had already copied the original class into its namespace,
      so `app = FastAPI(...)` at line 84 built an un-instrumented app.
- [x] Repro proving current code produces an un-instrumented app → 0 SERVER spans vs 1 with fix
- [x] Implement fix in `main.py` — `azure_monitor_configured` flag +
      `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")` (lines 23, 116-152)
- [x] Verify local — real `main.app` instrumented; 8/8 feature-area routes emit SERVER spans,
      0/2 health probes do; log `trace_id` now matches real span trace id
- [x] Verify live — ran real app against live `appi-invoicellm-dev`; `AppRequests` 0 → 4 rows with
      templated route names, 200/500/401, real durations, zero `/health` rows; feature-area KQL runs
- [x] Check other entrypoints — `queue_worker/main_worker.py` is not a FastAPI app, unaffected
- [x] Run backend test suite → 1003 passed, 3 failed (2 redis conn, 1 pre-existing signature drift),
      none related; new path is gated off during tests
- [x] Update `feature_20_observability_monitoring_alerts.md` (File Coordinates, narrative, Task 19.10)
- [x] Add Gap 292 entry to `be_features_tracker.md`

**Final status: complete.** Root cause was an import-order trap, not missing instrumentation.
Fix verified end-to-end against real Azure App Insights. Not deployed — `ca-invoice-be-dev` still
runs the pre-fix image. Two adjacent findings flagged but not fixed: `AppRoleName = unknown_service`
on all containers (infra scope), and two stale claims in the Feature 23 tracker entry.
