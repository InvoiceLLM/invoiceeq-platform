# senior-dev — Feature 23 Wave 1 telemetry prerequisites

Two pure-telemetry tasks. No agent behavior change. Leave uncommitted.

- [x] Read `.claude/CONVENTIONS.md` (done first, every time)
- [x] Read `be_features_tracker.md` Gap 304 / Gap 305 entries
- [x] Read `feature_23_ai_control_tower.md` for File Coordinates + verification-evidence style
- [x] Read `telemetry.py` — contextvar pattern, `track_agent_call()` attributes dict
- [x] Read `scripts/run_agent_eval.py` — `--run-label` plumbing confirmed present (line 1020)
- [x] Read `services/benchmark_artifacts.py::configure_run_telemetry()` — deferred export left unchanged, as scoped
- [x] Trace `agents/query_agent.py` call graph around line 1534
      → the SQL-gen `tracked_llm_call` (line ~1481) closes at `.invoke()`, *before*
      `execute_generated_sql()`, so the flag cannot ride that event. `chat.sql_summary`
      (line ~1710) is the turn's next event and fires exactly once per executed query.
      SAGE's `identify_invoices`/`aggregate` share the loop but make no follow-up LLM call
      → not covered, stated in the docs rather than papered over.
- [x] T1: `RUN_SOURCE_*` constants + `run_source_ctx` + `set_run_source()` +
      `_resolve_run_source()` in `telemetry.py`; `run_source` on `track_agent_call()`
- [x] T1: `configure_run_source(run_label)` in `benchmark_artifacts.py`, called from
      `run_agent_eval.py` and `run_extraction_benchmark.py` after `parse_args()`
- [x] T2: `zero_result` + `zero_result_fallback_recovered` on `SqlGenerationOutcome`,
      carried onto the existing `chat.sql_summary` call
- [x] Extend `tests/test_telemetry.py` — new "Gap 304 (partial)" (5 tests) and
      "Gap 305 (partial)" (5 tests) sections; 23 → 33
- [x] Run the suites: file 33 passed; 9-file adjacent sweep 344 passed / 5 skipped;
      full `tests/test_*.py` 1362 passed / 3 failed / 7 skipped, the 3 confirmed
      pre-existing by re-running them with all changes stashed. `ruff check` clean.
- [x] Fixed a real order-dependence the full run exposed: `test_run_extraction_benchmark_cli.py`
      runs the CLI in process, leaking `run_source=golden` into later tests; the default-value
      test now runs inside an empty `contextvars.Context()`.
- [x] Update tracker Gap 304 / Gap 305 — both stay `[ ]`, each gained an explicit
      "partial progress / what is NOT closed" paragraph
- [x] Update `feature_23_ai_control_tower.md` — new "Two telemetry prerequisites" section
      + Phase 1 event-field list, `run_query_agent()` row and test-count row corrected

Final status: complete. Both tasks built, tested and documented; changes left uncommitted.
Gap 304 and Gap 305 both remain open — only their prerequisites landed.
