# Gap 319 — persistence for the recommendation pass (B-track, item 3)

Scope: persist each nightly recommendation pass somewhere an Azure Monitor Workbook can query (a
custom event — a workbook cannot read Postgres). **Not** the Workbook panel (Gap 320), **no** bicep,
**no** workbook JSON edit, **no** `az` command.

- [x] 1. Read the tracker's Gap 318 (just closed) + Gap 319 entries and
      `feature_20_23_24_ops_workbook.md` item (b); confirmed the produced shape against the real
      `services/ops_recommendation.py::run_recommendation_pass()` rather than trusting the doc
- [x] 2. Read the emitter precedents in full — `telemetry.py`'s `_emit_event` / `track_agent_eval_summary`
      / `track_extraction_benchmark_run` / `track_online_signal` / `track_ops_digest_run` / `_truncate`
      + the `MAX_TURN_*` caps, and the mirror precedents `mirror_extraction_run` /
      `mirror_agent_eval_run` / `configure_run_telemetry` / `flush_run_telemetry` in
      `services/benchmark_artifacts.py`
- [x] 3. New event `ops_recommendation` in `telemetry.py`: `OPS_RECOMMENDATION_EVENT_NAME`,
      `track_ops_recommendation()`, the four bounding constants, `_finding_entry` / `_omitted_marker` /
      `_bounded_findings` (drops whole entries so the value stays valid JSON under App Insights'
      8,192-char property cap). One row **per category per run**, following `online_eval_signal`
- [x] 4. `mirror_recommendation_pass()` in `services/ops_recommendation.py` — returns `MirrorResult`,
      never raises, one shared `generated_at` across the run's three rows, `metrics` deliberately not
      mirrored
- [x] 5. Wired into `recommendation_pass_step()` in `scripts/run_agent_eval.py`: still nightly-only,
      still inside the swallow-everything wrapper, skipped under `--no-mirror`, and **flushed a second
      time** (main()'s mirror block has already flushed and the OTel exporter batches on a timer)
- [x] 6. Tests — 21 new: 8 in `tests/test_telemetry.py` (52 → 60), 7 in
      `tests/test_ops_recommendation.py` (64 → 71), 6 in `tests/test_run_agent_eval_cli.py` (13 → 19).
      Three events from a real pass result, shared run key, bounded/pathological findings, non-nightly
      and `--no-mirror` emitting nothing, fail-soft at both the emitter and the wiring level
- [x] 7. `pytest` on 7 affected files → **381 passed, 1 pre-existing skip**; re-run without
      `-p no:randomly` on the 5 telemetry-touching files → 197 passed; `ruff check` clean on all six
      touched files; mutation-checked the JSON-bounding loop and the second flush
- [x] 8. Updated `be_features_tracker.md` (Gap 319 → `[x]` with the full event schema, Gap 320
      unblocked with the KQL it needs) and `feature_20_23_24_ops_workbook.md` (item (b) → `[x]`,
      item (c)'s query, the Tasks checklist, and a `ops_recommendation` row in the
      real-data-vs-structurally-empty table)

Final status: **complete, uncommitted.** Code only — no `az` command was run and nothing was deployed.
`ops_recommendation` will be 0 rows in Log Analytics until a backend image carrying Gaps 308/317/318/319
is pushed and one nightly execution runs; Gap 320's panel must therefore handle the empty state.
