# senior-dev — Gap 304 half (1): export golden/predeploy eval telemetry

Scope approved by founder (architect-scoped). Close the code-level half of Gap 304 (1):
eval runs' own per-call telemetry now exports to App Insights, tagged by `run_source`.

- [x] 1. `telemetry.py::track_eval_result()` — `run_source` resolved via `_resolve_run_source()`,
      explicit keyword popped before the `**extra_attributes` loop
- [x] 2. `telemetry.py::_start_llm_dependency_span()` — `run_source` on the CLIENT span;
      `tracked_llm_call` passes an explicit value through with `.get()` so event and span agree
- [x] 3. `services/benchmark_artifacts.py::configure_run_telemetry()` — idempotent via
      `_exporter_attached`, `_BENCHMARK_INSTRUMENTATION_OPTIONS` (azure_sdk/psycopg2/requests/
      urllib/urllib3 off), `enable_live_metrics=False`, `enable_performance_counters=False`
- [x] 4. `scripts/run_agent_eval.py` — attach on the line after `configure_run_source()`,
      skipped under `--no-mirror`; mirror block re-call kept (now idempotent)
- [x] 5. `scripts/run_extraction_benchmark.py` — same
- [x] 6. Tests: +6 `tests/test_telemetry.py` (33→39), +6 `tests/test_benchmark_artifacts.py`
      (29→35), +2 `tests/test_run_extraction_benchmark_cli.py` (10→12)
- [x] 7. `uv run pytest tests/test_*.py -p no:randomly -q` → 1376 passed / 3 failed / 7 skipped;
      the 3 are the known pre-existing ones (2× test_connectors Redis, 1× test_rag stale
      `post_chat_message` signature), exactly +14 passed vs. the previous 1362 baseline.
      Mutation check: removing `run_source` from the span fails exactly the 3 span tests.
- [x] 8. `ruff check` clean on all 7 touched files
- [x] 9. Docs: feature_23 got a new "Gap 304 half (1)" section + 5 stale-claim corrections;
      feature_20 span-attribute line updated; tracker Gap 304 `[ ]` → `[~]` with a closing
      paragraph, and the Feature 23 mirror entry's "deliberately not fixed" line corrected

Final status: complete. Half (1) closed at code level; half (2) untouched; no live producer
of `golden`/`predeploy` events exists in Azure (`caj-benchmark-eval-dev` never deployed).
All changes left uncommitted.
