# senior-dev — Gap 323: `SCORE_BANDS` recalibration for `pass_rate` and `accuracy`

Task (founder-approved): the `d1-latest-pass-rate` and `d2-accuracy` bands are calibrated to what the
system happens to score today, not to what "good" means — tonight's real 25.7% pass rate and 0.600
accuracy both render green/blank. Recalibrate the two `SCORE_BANDS` entries in
`Prod_Invoice_LLM/apps/invoice-be/services/ops_recommendation.py` and fix the test-pinning gap.
**Python constant + its tests only** — the workbook JSON is infra-devops's mirror task (item 11 of the
2026-08-26 workbook redesign fix list).

- [x] Read `.claude/CONVENTIONS.md` and `active-work.md` (hard rule 5 — in-flight check)
- [x] Check `.claude/tasklists/` for overlap — `senior-dev-workbook-redesign-spec.md` (2026-08-26) is the
      direct predecessor and explicitly hands this off; no conflict
- [x] Read `services/ops_recommendation.py::SCORE_BANDS` + every read site
      (`evaluate_ai_improvement()` metrics loop line ~919, the grading loop line ~1058,
      `CONTEXT_DRIFT_BAND_KEY` line ~1012)
- [x] Read `tests/test_ops_recommendation.py::test_each_band_is_still_the_live_panels_band` — confirmed
      `accuracy` is **not** in the parametrize list (of the score bands, only `pass_rate` and
      `faithfulness` are pinned)
- [x] Read `decide_pass()` in `services/agent_eval.py` for what `pass_rate` actually is —
      `FAITHFULNESS_FLOOR = 0.80` AND `RELEVANCE_FLOOR = 0.70` AND `ACCURACY_FLOOR = 0.70`, per turn
- [x] Read the redesign section of `feature_20_23_24_ops_workbook.md` (findings 2 and 3, Fix 11)
- [x] Baseline run before touching anything: `pytest tests/test_ops_recommendation.py` → **83 passed**
- [x] Grep the repo for the old numbers / other couplings — found
      `infra/alert-ai-eval-critical-only.bicep` (Gap 299) hardcodes the red bands as bicep param defaults
      (`passRateRedBelow = '0.20'`, `accuracyRedBelow = '0.40'`); no test pins it, so nothing breaks, but
      it is a real infra-side mirror obligation to flag
- [x] Decide the numbers and write the reasoning down: **`pass_rate` (0.60, 0.75)**,
      **`accuracy` (0.75, 0.90)**
- [x] Change `SCORE_BANDS["pass_rate"]` and `SCORE_BANDS["accuracy"]`
- [x] Update the module docstring's threshold-provenance table + new "The two recalibrated bands (Gap 323)"
      section stating that these two are no longer a copy of a tile (the constant now leads and the JSON
      mirrors) — the module asserts in prose that every band is lifted from a live panel, so the exception
      has to be stated, not left to rot
- [x] Add `d2-accuracy` to `test_each_band_is_still_the_live_panels_band`'s parametrize list
- [x] Handle the transitional window: the JSON is not mine to change, so both recalibrated entries carry a
      `xfail(strict=True)` marker plus `test_the_two_recalibrated_bands_still_await_their_json_mirror`
      pinning the *stale* grid — the suite is green now and turns red the moment infra-devops mirrors,
      which forces the markers' removal
- [x] Update `_eval_payload()`'s `accuracy_mean` default (0.86 → 0.95) — it is the "every dimension green"
      fixture and 0.86 is yellow under the new band; `pass_rate` 0.87 needed no change
- [x] `pytest tests/test_ops_recommendation.py` → **84 passed, 2 xfailed in 33.81s** (baseline before the
      change: 83 passed)
- [x] Behaviour check on the real numbers that motivated the gap: a 35-turn payload with
      `pass_rate=0.257`, `accuracy_mean=0.600` now returns `recommend` with
      `pass_rate 0.257 red | below 0.60` and `accuracy 0.600 red | below 0.75` (previously both green)
- [x] `ruff check services/ops_recommendation.py tests/test_ops_recommendation.py` → All checks passed
- [x] Tracker: new `Gap 323` entry, `[x]`, exact values + reasoning + real pytest evidence; plus a pointer
      line on the workbook-redesign entry saying Fix 11's gap number is 323 and its code half is closed
- [x] `feature_20_23_24_ops_workbook.md`: additive note under Fix 11 (mirror table + reasoning + the three
      handover notes), a one-paragraph update on finding 2, and a `[~]` Fix 11 line in Tasks
- [x] Final status line below

**Final status: COMPLETE.** `SCORE_BANDS["pass_rate"] = (0.60, 0.75)`, `SCORE_BANDS["accuracy"] = (0.75, 0.90)`.
Two code files changed (`services/ops_recommendation.py`, `tests/test_ops_recommendation.py`), two docs
updated (`be_features_tracker.md` Gap 323, `feature_20_23_24_ops_workbook.md` Fix 11). No workbook JSON,
no bicep, no other `SCORE_BANDS` entry, no n=3-guard change. `pytest tests/test_ops_recommendation.py` →
84 passed, 2 xfailed (33.81s), baseline 83 passed; `ruff check` clean on both touched files. Changes left
uncommitted per repo rule. Two items handed to infra-devops: (1) mirror the two `thresholdsGrid`s, which
will turn the 2 strict xfails into failures — the fix then is to delete the markers and the transitional
test; (2) `infra/alert-ai-eval-critical-only.bicep`'s `passRateRedBelow` / `accuracyRedBelow` defaults
still read 0.20 / 0.40 and are pinned by no test at all.
