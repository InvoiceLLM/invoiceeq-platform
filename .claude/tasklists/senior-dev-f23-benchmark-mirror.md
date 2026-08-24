# senior-dev — Feature 23 benchmark result mirror (telemetry + blob artifacts)

Mirror both F23 benchmark tracks' results into Application Insights custom events (so a
workbook can query them) and push the full raw JSON to Blob Storage, following the
Feature 20 `azure_cost.py` / `sweep_azure_cost.py` precedent.

- [x] Read the source of truth: `benchmarks/extraction/metrics.py`, `scripts/run_extraction_benchmark.py`, `services/agent_eval.py`, `scripts/run_agent_eval.py`, `telemetry.py`, `services/azure_cost.py` + `scripts/sweep_azure_cost.py`
- [x] Check live: container `benchmark-artifacts` **does not exist** on `stinvoicellmdev2` (only `invoices`); `Storage Blob Data Contributor` **is** granted to `id-invoicellm-dev` at account scope — zero new RBAC needed
- [x] `telemetry.py`: `track_extraction_benchmark_run()` + `track_agent_eval_summary()`, event names `extraction_benchmark_run` / `agent_eval_summary`, plus `EVAL_SCORE_DIMENSIONS`
- [x] New `services/benchmark_artifacts.py`: blob upload + `mirror_extraction_run()` / `mirror_agent_eval_run()` + `configure_run_telemetry()` / `flush_run_telemetry()` (the exporter step a standalone script has to do for itself — without it nothing reaches `customEvents`)
- [x] `config.py` + `.env.example`: `BENCHMARK_ARTIFACT_CONTAINER`, `AZURE_STORAGE_ACCOUNT`, `BENCHMARK_ARTIFACT_UPLOAD`
- [x] Wire `scripts/run_extraction_benchmark.py` (`--run-label`, `--no-mirror`) — mirror runs before the gate verdict so a failing run still reports
- [x] Wire `scripts/run_agent_eval.py` (`--run-label`, `--no-mirror`) — fires independently of `--persist`, so gate runs are covered
- [x] Wire both callers: `infra/08-apps.bicep` + `infra/benchmark-eval-job-only.bicep` (`--run-label nightly`), `.github/workflows/deploy-dev.yml` (`--run-label predeploy`)
- [x] Tests: `tests/test_benchmark_artifacts.py` (29) + 2 new CLI non-fatality tests in `tests/test_run_extraction_benchmark_cli.py`
- [x] `uv run pytest` on the 7 affected files — 336 passed, 1 skipped; both bicep templates compile; workflow YAML parses
- [x] Real CLI runs: Track 1 `--mode verify --run-label predeploy` (exit 0, event emitted, upload failed non-fatally against a stopped local Azurite), Track 2 `--provider mock --run-label predeploy` (`agent_eval_summary` emitted)
- [x] Update `docs/feature_23_ai_control_tower.md` + `docs/feature_20_23_24_implementation_status.md` + `be_features_tracker.md`
- [x] Full backend suite re-run
- [x] Report findings

Final status: done, uncommitted. Two things that change the plan, both flagged in the
report: (1) the `benchmark-artifacts` container does not exist and is not declared in
`infra/modules/data/storage.bicep` — handled by create-on-first-use at runtime, with the
bicep declaration flagged as a decision rather than made; (2) neither benchmark script
ever called `configure_azure_monitor()`, so *no* telemetry from either job has ever
reached `customEvents` — the feature doc's claim to the contrary was stale, and is now
corrected in the doc and fixed in code.
