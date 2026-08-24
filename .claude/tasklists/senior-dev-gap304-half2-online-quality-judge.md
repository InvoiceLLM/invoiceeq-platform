# Gap 304 half (2) — production-turn quality judge (Feature 23)

Scope approved by founder: score every real production chat turn with the existing
reference-free judge, tagged `run_source=production`. In-process hook off the response
path, scores + `message_id` only (no customer text duplicated), `persona_score` included,
config-flag kill switch.

- [x] Read Gap 304 + feature_23 doc + all touched code (models, agent_eval, chat router,
      queue handler, query_agent, ops_digest_collect, online_eval_signals, telemetry)
- [x] `config.py`: `ENABLE_PRODUCTION_QUALITY_JUDGE` flag — default **False**, matching
      `ENABLE_ASYNC_CHAT_QUEUE`/`ENABLE_AGENTIC_SAGE`; checked in `submit_turn_judgement()`
      so off costs the turn nothing
- [x] `models.py::AgentEvalRun`: `run_source` (NOT NULL, default `golden`), `message_id`
      (nullable, no FK), `question`/`actual_answer` nullable +
      `ck_agent_eval_run_text_or_message`, `idx_agent_eval_run_source_time`
- [x] Alembic migration `a7c3d5e91f04`, chained onto `c4a91e77b208` (confirmed single head
      by walking every `down_revision`, then by `alembic heads`)
- [x] `agents/query_agent.py`: returns `judge_evidence` (SQL `db_result` / RAG chunk text +
      executed queries), attached after `set_cached_answer()` so the Redis payload is
      unchanged and cache hits are skipped; never persisted on `ChatMessage`
- [x] `services/online_quality_judge.py`: `judge_turn()` + `submit_turn_judgement()` —
      combined soft judge + persona + deterministic orchestration, writes the row, emits
      `track_eval_result(run_source=production)`, never raises
- [x] `routers/chat.py` sync path hook (existing `_chat_background_pool`), turn timed
- [x] `queue_worker/handlers.py::_execute` hook — same function, after commit +
      `complete_job()`, submitted not inline (tenant slot is held until the handler returns)
- [x] Consumer fix: `ops_digest_collect._eval_window_stats` filters `!= production`
      (otherwise `audit_job_failed` never fires again)
- [x] Consumer fix: `online_eval_signals._eval_run_notes` — rates were already tolerant,
      `eval_rows_in_window` was not; filtered at the query and documented
- [x] Tests: `tests/test_online_quality_judge.py` (20) + 3 `test_rag.py` + 2
      `test_chat_queue.py` + 2 `test_ops_digest.py` + 1 `test_online_eval_signals.py` = 28
- [x] `uv run pytest tests/test_*.py -q` → **1404 passed / 3 failed / 7 skipped**, exactly
      +28 vs the 1376 baseline; the 3 failures re-confirmed pre-existing from the run output
- [x] `ruff check` clean on all touched files (6 remaining findings in those files each
      verified pre-existing against the file's `HEAD` version)
- [x] Migration validated by actually running it: scratch SQLite at the exact pre-migration
      shape, `upgrade` + schema read-back + CHECK insert tests + `downgrade -1` round-trip,
      plus the Postgres DDL rendered offline
- [x] Docs: `feature_23_ai_control_tower.md` new "Gap 304 half (2)" section + Tasks entry +
      two stale half (1) statements corrected; tracker Gap 304 entry extended, marker kept
      `[~]`

Final status: complete. Gap 304 is now closed **in code** on both halves; the marker stays
`[~]` because neither half has a live producer — half (1)'s eval job has never been
deployed to Azure and half (2) ships behind a default-off flag. Changes left uncommitted.
