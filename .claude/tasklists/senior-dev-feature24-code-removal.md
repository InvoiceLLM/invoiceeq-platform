# Feature 24 (Ops Digest Agent) code removal

Superseded as over-scoped per 2026-08-25 decision. Design record preserved in git (`bce9e38`)
and in `docs/feature_20_23_24_ops_workbook.md`. Filed as BE **Gap 311**.

- [x] Baseline: `pytest tests/test_*.py` → **1449 passed / 3 failed / 7 skipped** (3 known pre-existing:
      2x `test_connectors.py` needs local Redis, 1x `test_rag.py` stale `post_chat_message` signature).
      Note: a plain `pytest` run collection-errors on `tests/us/run_chat_live_test.py` (basename clash
      with `tests/realworld_tenant/run_chat_live_test.py`) — pre-existing, unrelated, so the suite is
      run as `tests/test_*.py`, the same invocation the tracker's prior entries used.
- [x] Audit `emit_online_signals` caller — lived in `ops_digest_job.py::_compute_online_signals()` /
      `_emit_online_signals()`, called from `main()` after `configure_telemetry()`. Never live-scheduled
      (`caj-ops-digest-dev` was never deployed).
- [x] Confirm `infra/modules/monitoring/dashboard.bicep` unreferenced — no `module … dashboard.bicep`
      anywhere in `infra/`; only 2 prose comments (`alert-rules.bicep`, `workbook-cost-health-only.bicep`).
- [x] Extract standalone `scripts/emit_online_signals_job.py` (`--window-hours` / `--dry-run` / `--json`)
- [x] Move test coverage → `tests/test_emit_online_signals_job.py`, **8 passed**
- [x] Delete 4 `services/ops_digest*.py`
- [x] Delete 2 `tests/test_ops_digest*.py` (76 tests)
- [x] Delete `scripts/ops_digest_job.py`
- [x] Delete `infra/ops-digest-job-only.bicep`
- [x] Delete `infra/modules/monitoring/dashboard.bicep`
- [x] `infra/08-apps.bicep`: dropped `opsDigestJob` module + `opsDigestCron`/`opsDigestDelivery` params
- [x] Removed 7 `OPS_DIGEST_*` settings from `config.py` (+ mirrored out of `.env.example`)
- [x] `Monitoring Reader` RBAC kept — comment rewritten to say why; resource byte-identical
- [x] Repo-wide grep: zero remaining imports; stale prose pointers fixed in `online_eval_signals.py`,
      `telemetry.py`, `benchmark_artifacts.py`, `models.py`, `online_quality_judge.py`,
      `test_online_eval_signals.py`, `chat_thread_sessions.kql`, `alert-rules.bicep`,
      `workbook-cost-health-only.bicep`, `benchmark-eval-job-only.bicep`.
      Deliberately not touched: `agents/query_agent.py` (out of scope, active SAGE work) and the
      alembic migration `a7c3d5e91f04` (migrations are an immutable record).
- [x] `az bicep build` clean on every top-level template in `infra/` (only the two pre-existing
      warnings: `front-door.bicep` BCP081, `invoice-be.bicep` BCP037)
- [x] Re-run `pytest tests/test_*.py` → **1381 passed / 3 failed / 7 skipped** (= 1449 − 76 + 8), same
      3 pre-existing failures, nothing new broken
- [x] Fixed dead file-path refs in `docs/feature_20_23_24_ops_workbook.md` ("The digest build, superseded")
- [x] Filed **Gap 311** in `docs/be_features_tracker.md`

Final status: complete. Nothing committed — all changes left in the working tree.
