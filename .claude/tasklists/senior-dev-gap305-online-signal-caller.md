# senior-dev — Gap 305: give `emit_online_signals()` a scheduled caller

Scope (Wave 2, architect-scoped): wire `services/online_eval_signals.py::emit_online_signals()`
into the existing Feature 24 digest job rather than standing up a new Container App Job.

- [x] 1. Read Gap 305 + Gap 304 tracker entries, `services/online_eval_signals.py` in full,
      `scripts/ops_digest_job.py::main()`, `services/ops_digest_collect.py::_collect_online_signal_items()`
- [x] 2. Cadence verified **in the bicep**, not taken from the gap text:
      `infra/08-apps.bicep::opsDigestCron` = `0 1,7,13,19 * * *` UTC (every 6h, matches
      `OPS_DIGEST_WINDOW_HOURS=6`). Also confirmed `caj-ops-digest-dev` has never been deployed.
- [x] 3. `scripts/ops_digest_job.py::_compute_online_signals()` — computes inside the existing
      `run_ops_digest()` try/finally while the session is open; naive-UTC boundary conversion;
      `window_days` = the digest's own fractional window; returns `(None, None)` on any failure
- [x] 4. `scripts/ops_digest_job.py::_emit_online_signals()` — called after `configure_telemetry()`
      (exporter must be attached first) and after `track_ops_digest_run()`; never raises
- [x] 5. `telemetry.py::track_online_signal()` — `window_days` int→float; `int(0.25)` was `0`
- [x] 6. `services/online_eval_signals.py::emit_online_signals()` docstring: "Not wired to anything
      yet" replaced with the real caller/cadence; `window_days` retyped `Optional[float]`
- [x] 7. Tests: +7 `tests/test_ops_digest.py` (real `main()`, real SQLite, real ChatMessage/
      ChatFeedback rows), +1 `tests/test_online_eval_signals.py` (fractional window on the event)
- [x] 8. `uv run pytest tests/test_*.py` → **1412 passed / 3 failed / 7 skipped** = exactly +8 vs.
      the 1404 baseline; same 3 pre-existing failures (2× test_connectors Redis, 1× test_rag stale
      `post_chat_message` signature). Mutation checks: deleting the emit call fails exactly 4 new
      tests; restoring `int(window_days)` fails exactly the 2 window tests.
- [x] 9. `ruff check` clean on all 5 touched files
- [x] 10. Docs: `feature_23_ai_control_tower.md` new "Gap 305 — `emit_online_signals()` has a
      scheduled caller (2026-08-24)" section + 4 stale-claim corrections; tracker Gap 305
      `[ ]` → `[~]` with a closing paragraph

Final status: complete. `emit_online_signals()` no longer has zero callers — all five signals have
a live emission path in code. **Not verified live**: `caj-ops-digest-dev` has never been deployed,
so no `online_eval_signal` event exists in Azure, and no workbook reads the event either. All
changes left uncommitted.
