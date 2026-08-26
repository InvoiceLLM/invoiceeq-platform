# senior-dev — Gap 307, offline context-drift detection (golden-bank multi-turn tier)

Scope, as approved: **offline only**. A multi-turn tier in the existing eval golden bank plus a
deterministic drift score, wired into the nightly job the way the other tiers already run. The
**online** half (a live judge over production `chat_turn` events) is explicitly deferred and gets its
own gap number — recommended in the tracker, not built here.

Out of scope, confirmed against `active-work.md`: no online judge, no new telemetry *event*, no new
Azure resource, no bicep, nothing in SAGE Phase 3 or Gap 306 territory.

## Steps

- [x] Read `.claude/CONVENTIONS.md`, `active-work.md`, in-flight tasklists (7-day window)
- [x] Confirm Gap 307's own definition of "context drift" against the tracker +
      `feature_20_23_24_ops_workbook.md` — verified: the failure class is Gap 237 (a narrowing follow-up
      silently dropping a filter branch) and Gap 276 (the prior turn's SQL reused after a topic change),
      and the doc's own recommendation is "fixed 2-3 turn scripts with pinned expectations", not a
      general detector
- [x] Read the Wave 3 precedent (`benchmarks/agent_eval_golden_sample.py`, `region_seed_fixtures.py`,
      `scripts/run_agent_eval.py`, `services/agent_eval.py`, `services/ops_recommendation.py`) and follow
      its structure rather than inventing one
- [x] Decide the integration shape (drift as a **deterministic component-level** score next to
      `context`/`orchestration`, no judge call; graded on `d3-context`'s existing workbook band so no
      un-pinned threshold is invented)
- [x] `services/benchmark_artifacts.py` — `MULTI_TURN_PATH`, shared vocabulary between the runner and
      the ops pass (the role `RUN_LABEL_*` already plays)
- [x] `services/agent_eval.py` — `DriftExpectation`, `score_context_drift()`,
      `EvalScores.context_drift_score`, wired through `score_answer()`; deliberately NOT in
      `decide_pass()`. Three checked surfaces (prose+SQL / SQL-only / prose-only) so a chatty-but-
      correct answer is not scored as drifted
- [x] `benchmarks/agent_eval_multiturn.py` — 5 scripts / 12 turns / 7 drift-scored turns, every
      expectation pinned to a seeded row
- [x] `benchmarks/agent_eval_golden_sample.py` — `GoldenCase.drift` field (additive, None on all 35)
- [x] `telemetry.py` — `context_drift` added to `EVAL_SCORE_DIMENSIONS` (no new event; the emitter
      already drops None dimensions, so the `default` bucket's event is unchanged)
- [x] `scripts/run_agent_eval.py` — shared-session multi-turn loop, `ChatMessage` write-back between
      turns, its own summary bucket, `--no-multi-turn`, drift in `summarise()`/`persist()`/telemetry
- [x] `services/ops_recommendation.py` — `context_drift` finding in `evaluate_ai_improvement()`,
      graded on `d3-context`'s band; `_multi_turn_stats()`; `_agent_eval_stats()` now excludes the
      drift bucket from its path choice
- [x] Tests: `tests/test_agent_eval_multiturn.py` (new, 40) + `test_ops_recommendation.py` (+9) +
      `test_benchmark_artifacts.py` (+1, one existing test re-anchored to "dimensions actually
      scored") + `test_run_agent_eval_cli.py` (tier stubbed out of `_run_main`, or a CLI test would
      make 12 real model calls)
- [x] Run the affected test files only — 43 + 83 + 40 + 19 + 97 + 60 = **339 passed, 0 failed**
      (`test_agent_eval_multiturn` / `test_ops_recommendation` / `test_benchmark_artifacts` /
      `test_run_agent_eval_cli` / `test_agent_eval` / `test_telemetry`). Full suite deliberately not
      run — reserved for a track-boundary checkpoint.
- [x] Real dry run against the real Azure judge — **two live runs**, `--no-persist --no-mirror`:
      - **Run A** (all 5 scripts): 12/12 turns, 0 errors, $0.005/turn; `default-multiturn` bucket
        `pass_rate 0.333`, `faithfulness_mean 0.806`, `accuracy_mean 0.742`,
        **`context_drift_mean 0.943` over 7 scored turns**. 6/7 turns at 1.00; the June scope and the
        >USD 20,000 filter both visibly survived in the generated SQL two and three turns later.
      - **The 7th (0.60) was a defect in my own check, found by running it**: a correct clarifying
        question named both invoices by NUMBER while the check demanded vendor NAMES →
        `required_terms` replaced by `required_entities` (alias groups), exact answer text pinned as
        a regression test.
      - **Run B** (same script, after the fix): the model silently resolved "the previous invoice"
        to DPS-9981 → `context_drift 0.80`, note "the subject under discussion went missing:
        StratEdge/SEP-4410", independent accuracy judge `0.0`. True positive kept.
- [x] Docs: `be_features_tracker.md` Gap 307 → `[x]` with the full closure + **Gap 321 recommended**
      for the deferred online judge (stated as NOT part of this closure);
      `feature_20_23_24_ops_workbook.md` → additive tier section + additive field-table row.

## Final status

**Done.** Offline tier built, unit-tested and dry-run live against the real judge. The online judge is
**not** built and is recommended as **Gap 321** — 320 is the current tracker maximum. No new telemetry
event type, no Azure resource, no bicep, nothing in SAGE Phase 3 or Gap 306 touched. Changes left
uncommitted.
