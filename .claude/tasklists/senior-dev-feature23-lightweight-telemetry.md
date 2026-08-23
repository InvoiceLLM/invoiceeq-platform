# senior-dev — Feature 23 lightweight-tier telemetry (Trainer/EVOLVE, Dashboard insights, Trainer QA-summary)

Scoped as "three registry rows have no telemetry, add hard-metrics-only coverage".
Note: this file was created part-way through the run, after the verification step
below had already turned the task from "add instrumentation" into "prove the
existing instrumentation and correct the doc". Recorded honestly rather than
back-dated.

- [x] Read `.claude/CONVENTIONS.md` and `feature_23_ai_control_tower.md`'s 2026-08-23 section
- [x] Read `telemetry.py` in full — `track_agent_call()` / `tracked_llm_call()` / `resolve_model_name()` / `LlmUsage`
- [x] Grep every `tracked_llm_call`/`track_agent_call` site outside `tests/`
- [x] Grep every `get_llm(` / `with_structured_output(` / `.invoke(` site outside `.venv/`, `tests/`, `scripts/`
- [x] **Verify call site 1 — Trainer/EVOLVE**: `agents/trainer_agent.py::refine_constraints` → `trainer.refine_constraints` **already instrumented**; also `routers/trainer.py::flag_missed_alert` → `trainer.missed_alert_rule` and `::_validate_rule_text` → `trainer.rule_guardrail`, both already instrumented
- [x] **Verify call site 2 — Dashboard insights**: `routers/dashboard.py::get_dashboard_insights` → `dashboard.insights` **already instrumented** (registry table's "needs coverage" framing was stale)
- [x] **Verify call site 3 — Trainer QA summary**: `routers/trainer.py::_answer_qa_from_session_data` → `trainer.qa_summary` **already instrumented**
- [x] Confirm `tenant_id` is threaded to all five (not relying on the middleware contextvar, which never sets it)
- [x] Decide: add **no** instrumentation (would duplicate); add the missing **test** coverage instead
- [x] Read `tests/test_telemetry.py` for the existing pattern (caplog + `_events()` + field assertions)
- [x] Add 9 call-site coverage tests to `tests/test_telemetry.py` (5 → 14)
- [x] Run `uv run pytest tests/test_telemetry.py -p no:randomly -q` → 14 passed
- [x] Mutation-check: strip the wrapper from `get_dashboard_insights` → 2 fail; restore → 14 pass
- [x] Run adjacent suites `tests/test_telemetry.py tests/test_trainer.py tests/test_dashboard.py` → 89 passed (169s)
- [x] Correct the registry table in `feature_23_ai_control_tower.md` (named function + `agent_name` per row; added the missing `trainer.rule_guardrail` and offline `eval.*` rows)
- [x] Correct the 2026-08-23 Scope subsection's "missed entirely" claim (missed from the *parameter design*, not from telemetry)
- [x] Add "Lightweight-tier coverage verified (2026-08-23)" narrative section + update the Phase 1 file-coordinates test-count row
- [x] Add the dated `be_features_tracker.md` entry

**Final status:** complete. Zero application-code changes — no instrumentation was missing. One test
file extended (9 new tests), two docs corrected. Changes left uncommitted.
