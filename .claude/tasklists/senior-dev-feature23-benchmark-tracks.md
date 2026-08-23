# Feature 23 — Audit/benchmark, 2 tracks (senior-dev)

Scope from `feature_23_ai_control_tower.md`'s 2026-08-23 "Audit / benchmark process — 2 tracks".

## Track 1 — extraction & alerts (net new)

- [x] `tests/extraction_benchmark/documents.py` — `InvoiceSpec` + deterministic OCR renderer, 4 clean docs with ground truth
- [x] `tests/extraction_benchmark/mutations.py` — 11 named mutators, 13 seeded cases, correct-vs-planted recorded per case
- [x] `tests/extraction_benchmark/metrics.py` — field accuracy, alert recall/precision, FP rate, confusion matrix
- [x] `tests/extraction_benchmark/harness.py` — verify (deterministic) + live (real LLM) modes over `agents/extraction_agent.py`
- [x] `tests/extraction_benchmark/artifacts.py` + `scripts/run_extraction_benchmark.py`
- [x] Review artifacts under `docs/extraction_benchmark/` (README + case_manifest.md/json + 17 documents/ + runs/)
- [x] `tests/test_extraction_benchmark.py` — 115 passed, 1 skipped
- [x] Run verify-mode for real: alert recall 13/13 = 100%, clean FP 1/4 = 25%, 0 collateral
- [x] Run live-mode for real: field accuracy 81/81 = 100%, recall 5/5 (8 n/a), same 1 FP
- [x] Gate exit code checked directly: 1 with the FP present, 0 with `--no-gate`
- [x] Real defect found: discounted OUTBOUND invoice always alerts (schema has no discount field) -> Gap 293
- [x] Cadence blocker confirmed against `.dockerignore`: `**/tests/` + `docs/` excluded, so no ACA job can run either track

## Track 2 — SAGE chat

- [x] Extend `tests/agent_eval_golden_sample.py` case set 11 -> 20 (added, all 11 originals kept)
- [x] `services/agent_eval.py` — `CombinedSoftVerdict` + `_build_combined_prompt()` + `score_soft_metrics_combined()`
- [x] Wire into `score_answer(combined_judge=)` + `run_agent_eval.py --judge separate|combined`
- [x] Extend `tests/test_agent_eval.py` — 91 passed (35 new)
- [x] Run combined for real (20 turns, live gpt-5-mini)
- [x] Run separate for real over the same 20 cases for comparability
- [x] Found by running: completeness had failure-mode-4's shape (a correct refusal is
      definitionally incomplete). Fixed with `COMPLETENESS_KIND_SCORES`, same classify-then-fix
      mechanism as relevance, + 5 tests
- [x] Re-run combined post-fix: `internals_probe_no_leak` completeness 0.00 -> 1.00, verified live
- [x] Found by running: the chat path pastes raw (and sometimes fabricated) SQL into user-facing
      answers -> Gap 294. Tone caught it 1 of 3 times; faithfulness caught the worse instance.
      Reported as observed, not written up as a win for the new metric.

## Docs

- [x] `feature_23_ai_control_tower.md` — "Track 1 as built", "Track 2 as built", "The cadence blocker",
      "Still open after this pass"
- [x] `be_features_tracker.md` — 2 dated feature entries + Gap 293 + Gap 294
- [x] Full backend suite: 1248 passed, 3 failed (all pre-existing/unrelated), 7 skipped

Final status: both tracks built, both really run, both measured. Two real product defects found and
filed unfixed (Gaps 293, 294) plus one judge defect found and fixed. Left uncommitted.
