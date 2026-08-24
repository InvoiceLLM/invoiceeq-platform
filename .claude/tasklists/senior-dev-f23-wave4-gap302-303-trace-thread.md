# senior-dev — Feature 23 Wave 4: Gap 302 (Trace) + Gap 303 (Thread)

Started 2026-08-24. Founder decisions: full-content trace capture, judge-attribution fix folded in,
30-min thread idle cutoff.

- [x] Establish real test baseline — **1411 passed / 4 failed / 7 skipped** (clean run, 466s).
      4 pre-existing failures: 2x `test_connectors.py` (needs local Redis), 1x `test_rag.py`
      (`post_chat_message()` without `background_tasks`), 1x `test_agent_eval.py`
      (`test_every_expected_invoice_number_exists_in_the_seeded_fixture` — new today, from the
      parallel region-golden-cases work, not mine).
- [x] Read ground truth: telemetry.py, query_agent.py, routers/chat.py, queue_worker/handlers.py,
      sage_orchestrator.py, online_quality_judge.py, agent_eval.py, main_worker.py
- [x] Confirmed `infra/monitoring/ai_control_tower.workbook.json` absent — `git log` shows it
      deleted in `bd6a255`; `infra/monitoring/` holds only cost_health_workbook.json + 2 .kql
- [x] App Insights retention: workspace-based component (`WorkspaceResourceId` +
      `IngestionMode: LogAnalytics`), so `customEvents` inherit LAW retention =
      `06-compute-env.bicep::logRetentionInDays` → **30d dev / 90d prod**. No table-level
      override, no purge/export policy anywhere in `infra/`.
- [x] Parallel Gap 305 wiring already landed in `scripts/ops_digest_job.py` — NOT touched
- [x] Gap 302: telemetry.py — `chat_turn` event, `ChatTurn` accumulator, `chat_turn_scope()`,
      `current_chat_turn()`, `track_chat_turn()`, `_truncate()`, MAX_TURN_* caps, TURN_STATUS_*
- [x] Gap 302: query_agent.py — `run_query_agent()` split into a Trace wrapper + `_run_query_agent`
      body; all 3 return paths (SAGE / cache hit / normal) populate the turn; `SqlGenerationOutcome`
      gained `attempts`
- [x] Gap 302: routers/chat.py + queue_worker/handlers.py emit on success AND on their own
      exception path
- [x] Judge-attribution fix: `utils/logging_config.py::correlation_context()`;
      `handle_process_chat_job(trace_id=, request_id=)`; `judge_turn(trace_id=, request_id=)`
- [x] Gap 303a: `turn_index` + `seconds_since_prev_turn` via
      `query_agent.py::_session_turn_position()`
- [x] Gap 303b: **pure KQL derivation, no new job** —
      `infra/monitoring/chat_thread_sessions.kql` using `row_window_session(..., 30m)`
- [x] Tests: 13 new in tests/test_telemetry.py (39 → **52**); parity harness/test updated for the
      new non-deterministic return key
- [x] `ruff check` on all 9 touched files — 3 findings, all confirmed pre-existing by running ruff
      against each file's HEAD version
- [x] Full suite re-run and diffed against the baseline
- [x] Docs: tracker Gaps 302/303/304/305 + new Gap 307; feature_23 Observability primitives +
      stale workbook claim corrected; feature_20_23_24 status

Status: complete. Nothing committed; changes left in the working tree.
