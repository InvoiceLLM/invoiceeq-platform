# Gap 318 — the Feature 20/23/24 recommendation pass (B-track, item 2)

Scope: build the check-and-flag recommendation pass (3 categories: container health, cost,
AI improvement), wire it into the nightly `--run-label nightly` path of
`scripts/run_agent_eval.py`, test it. **Not** persistence (Gap 319), **not** the Workbook panel
(Gap 320), **no** Azure deploy.

- [x] 1. Read the tracker's Gap 318 entry + `feature_20_23_24_ops_workbook.md` design sections
- [x] 2. Read the real code/data sources: `services/azure_cost.py`, `scripts/run_agent_eval.py`,
      `scripts/run_extraction_benchmark.py`, `services/benchmark_artifacts.py`, both workbook JSONs
      (thresholds pulled out of every relevant `thresholdsGrid`), the deleted `ops_digest_collect.py`
      (ARG call pattern + `_arg_rows`, git `bce9e38`)
- [x] 3. Wrote `services/ops_recommendation.py` — `evaluate_container_health` / `evaluate_cost` /
      `evaluate_ai_improvement` / `collect_container_health` / `parse_container_metrics` /
      `run_recommendation_pass`; `RecommendationPass` → `CategoryRecommendation` → `Finding`;
      4 statuses (worked / recommend / no_data / insufficient_data)
- [x] 4. Track 1 handoff: confirmed the two tracks are two processes (`&&` in the job args), added
      `track1_handoff_path` / `write_track1_handoff` / `read_track1_handoff` to
      `services/benchmark_artifacts.py` (stale + wrong-cadence rejection), written by Track 1
      independently of `--no-write`
- [x] 5. Wired `recommendation_pass_step()` into `run_agent_eval.main()` — last step, nightly-only,
      swallows its own exceptions
- [x] 6. Tests: `tests/test_ops_recommendation.py` (64) + 4 in `tests/test_run_agent_eval_cli.py`
      — real boundary values per band, workbook-parity test that re-reads both JSONs, nightly-only
      wiring, fail-soft isolation, handoff staleness
- [x] 7. `pytest` on 7 affected files → 360 passed / 1 pre-existing skip; `ruff check` clean on all
      six touched files; mutation-checked the nightly gate and one threshold
- [x] 8. Updated `be_features_tracker.md` (Gap 318 → `[x]`, Gap 319 unblocked) and
      `feature_20_23_24_ops_workbook.md` (item (a) → `[x]` with what was actually built, item (b)'s
      consumable shape, the Tasks checklist, and the sample table's "judgement spec, not output
      schema" clarification)

Final status: **complete, uncommitted.** Code-only — no `az` command was run and nothing was deployed;
the container-health category is unproven against live Azure until the undeployed `Monitoring Reader`
grant lands, and degrades to `no_data` by design until then.
