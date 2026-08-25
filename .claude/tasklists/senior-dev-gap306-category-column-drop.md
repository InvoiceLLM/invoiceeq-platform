# Gap 306 — rule 6b's four-column OR group is emitted with `items` dropped

Structural fix only (active-work.md: "known, deliberately NOT fixed; fix must be
structural, no quick patches"). No new prose on rule 6b.

- [x] Read Gap 306 + Gap 316 tracker entries, rule 6b as it stands today, `sage_prompts.py`'s reflection half
- [x] Baseline full suite before any change — **1316 passed / 2 failed / 1 skipped** (both failures pre-existing: `test_extraction_benchmark.py::test_regenerating_the_corpus_is_byte_identical`, `test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message`)
- [x] Reproduce: the emitted group (tags/sa_alerts/vendor_name/customer_name) returns `[]` against a row whose phrase lives only in `items`; the mandated group returns `KE-2026-0089`. Executed, then shipped as `test_the_dropped_items_column_is_what_misses_the_invoice`
- [x] Investigate the SAGE lead — **it fits, but not as a prompt substitution.** Reflecting 18 columns *into* the prompt would make the model's job harder, not easier. The reflection is used to build and *execute* the clause in code instead
- [x] Implement: `sage_prompts.category_match_branches()` / `category_match_expression()` / `category_match_json_columns()` (executable siblings of the text renderer, one shared `_category_match_columns_typed()` pass) + `query_agent.recover_missed_category_match()` / `category_search_phrases()` / `category_search_fallback()` / `_direction_in_generated_sql()`, wired into `run_sql_generation_loop()`'s zero-result branch after the invoice-number fallback. `render_result_cell()` extracted from `execute_generated_sql()` so both tables render identically. **Rule 6b's prompt text unchanged.**
- [x] Tests: 19 new tests / 21 cases in `tests/test_chat_sql_quality.py`; both end-to-end tests confirmed to FAIL with the fallback call disabled
- [x] Narrow run (`test_chat_sql_quality` 136 passed; + telemetry/query_tools/direction_aware/rag/chat_training → 309 passed / 1 failed, the standing `background_tasks` one)
- [x] Full suite checkpoint — **1338 passed / 1 failed / 1 skipped**, run twice, identical
- [x] `ruff check` clean on `agents/query_agent.py`, `agents/sage_prompts.py`, `tests/test_chat_sql_quality.py`
- [x] Tracker Gap 306 → `[x]`; `feature_6_rag.md` File Coordinates (both `query_agent.py` and `sage_prompts.py` lines), a new "Recent Fix (Aug 25, 2026) — Gap 306" section, and a Verification Plan bullet

**Final status: done, uncommitted.** Two things flagged for the founder rather than acted on: (1) `active-work.md`'s "Frozen / do not touch" list still says Gap 306 is deliberately not fixed — agents do not edit that file, so it needs a founder pass; (2) Gap 316's founder call on `sage_prompts.py` is now *half* answered — the reflection half is imported and tested, `IDENTIFY_*`/`AGGREGATE_*`/`build_identify_system_prompt()`/`build_aggregate_system_prompt()`/`aggregate_schema_block()` still have zero callers and zero tests.
