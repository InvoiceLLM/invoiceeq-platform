# Feature 23 Wave 2 — two live-found nightly-job defects

Found by actually running `caj-benchmark-eval-dev` in Azure, not by inspection.

## Investigation
- [x] Read `infra/benchmark-eval-job-only.bicep` + `08-apps.bicep` `benchmarkEvalJob` — persisted nightly args confirmed identical in both, no `--out` on Track 2.
- [x] Read `scripts/run_agent_eval.py` — `OUTPUT_PATH = _BE_ROOT / "tests" / "agent_eval_output.json"`, `default_output_path()` at L539.
- [x] Confirm `.dockerignore` strips `**/tests/` (line 47) — `/app/tests/` does not exist in the image.
- [x] Check `run_extraction_benchmark.py` for the same class of bug — it has no `--out`; writes only under `--no-write`-guarded `write_run_artifacts()` (and `write_corpus_artifacts()` which mkdirs its own tree). Not affected.
- [x] Check what depends on `tests/agent_eval_output.json` — 6 committed run-output JSONs live there, docs quote the path, `test_model_substitution.py` asserts on the *filename* only.
- [x] Confirm the pre-deploy gate already passes `--out /tmp/agent_eval_gate.json` (deploy-dev.yml L237) — only the nightly path lacks one.
- [x] Root-cause Defect 2 — NOT the exporter, NOT the flush: `invoice_be_telemetry`'s effective log level is WARNING in `run_extraction_benchmark.py`'s process, so `_emit_event()`'s `.info()` record is dropped before any handler sees it. Verified live: `getEffectiveLevel() == 30`, `isEnabledFor(INFO) == False` under that script's exact import chain. `configure_azure_monitor()` adds a handler but never sets a level (verified in the installed distro, `_configure.py` L275-290).
- [x] Confirm why Track 2 works — `run_agent_eval.py::_counting_llm_calls()` calls `lg.setLevel(logging.INFO)` on both event loggers and never restores it, so Track 2 is accidentally saved. `sweep_azure_cost.py`/`ops_digest_job.py` are saved by `setup_structured_logging()` (root at INFO).

## Baseline
- [x] Re-verify today's baseline before changing anything — **the claimed `1414 passed / 7 failed` is stale**. Real: **1431 passed, 3 failed, 7 skipped** in 406s. The 3: 2 × `test_connectors.py` (needs local Redis), 1 × `test_rag.py` (`post_chat_message()` gained `background_tasks`).

## Fixes
- [x] Defect 1 — `scripts/run_agent_eval.py`: new `default_output_dir()` returns `tests/` when it exists (every checkout — local dev unchanged) and `tempfile.gettempdir()` when it does not (the image). Chosen over a bicep `--out` override: no redeploy, and the script default stops being a trap for the next caller.
- [x] Defect 2 — `services/benchmark_artifacts.py`: new `_enable_event_logger_level()`, called first thing in `configure_run_telemetry()`. Root cause was `logging`'s own level check, not the exporter or the flush.

## Tests
- [x] `tests/test_run_agent_eval_cli.py` (new, 7) — real `main()` on the literal nightly argv with `CASES` emptied; 2 of them read both bicep files and fail if either gains an `--out`.
- [x] `tests/test_benchmark_artifacts.py` (+4) — premise (INFO event reaches no handler at default levels), fix, no-exporter path, DEBUG survives.
- [x] `tests/test_run_extraction_benchmark_cli.py` (+1) — real `main()`, recording handler where the distro attaches its own.
- [x] Both fixes reverted to prove the tests fail without them. Gap 308's reproduces the live `FileNotFoundError` exactly.
- [x] Full suite: **1443 passed, 3 failed, 7 skipped** (410s) — +12 = exactly the new tests, same 3 pre-existing failures.
- [x] `ruff check` clean on all 5 touched files.

## Docs
- [x] `be_features_tracker.md` — new Gap 308 + Gap 309 entries in the Feature 23 section; the mirror entry's "Not verified: anything arrives in customEvents" corrected.
- [x] `feature_23_ai_control_tower.md` — new "What the first real deployed run found — two defects" section; the stale nightly command block in the scheduler section updated to the args actually persisted.

Final status: both defects fixed in application code, everything uncommitted. **No bicep changed, so no `az deployment group create` is needed** — the job pins `invoice-be:latest` and `deploy-dev.yml` sets `also_tag_latest: true`, so a CI backend build containing this commit takes both fixes live on the next execution. Not verified and not verifiable from the test suite: that `extraction_benchmark_run` actually lands in `customEvents` — that needs that build plus one more real run.
