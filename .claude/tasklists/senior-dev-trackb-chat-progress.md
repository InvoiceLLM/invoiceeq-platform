# senior-dev — Track B (Gap 365): live chat progress + flip criteria + per-session lock

Scope from `.claude/tasklists/architect-phase2-sage-feature-build.md` "TRACK B".
Do-not-touch: `services/chat_queue.py`, `routers/chat.py`, `tests/test_chat_queue.py`
(Track A), any FE file, the flag's actual value. All honoured.

- [x] B1. `agents/query_agent.py`: optional `on_progress` on `run_query_agent()` /
      `_run_query_agent()` / `run_sql_generation_loop()` (the per-attempt seam lives
      inside the loop), default None = no-op via `_progress_emitter()`.
- [x] B2. 12 seams declared once in `_PROGRESS_STEPS`; `generating_sql` fires once
      per attempt; `route_override` publishes before `route` is reassigned so the
      overridden-from route is visible. Details are scalars only — no SQL, no model
      prose, no tenant id (Gap 294 discipline, enforced by not publishing internals
      rather than by a second redactor).
- [x] B3. `queue_worker/handlers.py`: `on_progress` closure → `publish_progress()`,
      same shape as ingestion's `on_log`. Handler owns UI copy
      (`_CHAT_PROGRESS_MESSAGES`, "(retry N)" past attempt 1). The 2 hardcoded steps
      became 2 honest handler bookends (`received`/`saving`) — deviation recorded in
      the Gap entry.
- [x] B4. `config.py`: D7's 5 flip criteria written into the docstring.
      **Value left `False`.**
- [x] B5. `chat_session_lock()` in `handle_process_chat_job` — the single funnel for
      all 3 call sites. SET NX + token-checked release, 300s TTL, 120s wait, degrades
      to unserialised on Redis-down/timeout rather than dropping the turn.
- [x] B6. New `tests/test_chat_progress.py` — 13 tests: seams + order, per-attempt
      retries, RAG count, override visibility, no-internals, raising-callback,
      no-callback-identical, same-session serialisation, cross-session parallelism,
      release on normal/raising path, Redis-down, wait timeout.
- [x] Tracker Gap 365 filed (fresh collision check at write time: max was 364, Track A
      had already filed it). Stale Gap 280 bullet corrected in place. Spec doc
      `feature_6_rag.md` updated (Recent Change + Verification Plan bullet).
- [x] Narrow tests run: `test_chat_progress.py` 13 passed; regression
      `test_telemetry/test_query_tools/test_turn_drift` 97 passed;
      `test_chat_queue/test_chat_sql_quality` 155 passed;
      `test_queries/test_rag/test_direction_aware_chat/test_chat_training` 102 passed
      + 1 pre-existing failure (`test_process_crash_during_agent_leaves_no_orphan_user_message`,
      unrelated, unchanged from HEAD).

**FINAL STATUS (2026-09-01): Track B COMPLETE.** All six items shipped, uncommitted.
Flag remains `False` by design — clearing the 5 criteria is Phase 3 / T4's call, and
nothing here is Postgres-backed evidence (mocked LLM, SQLite, fake Redis).
