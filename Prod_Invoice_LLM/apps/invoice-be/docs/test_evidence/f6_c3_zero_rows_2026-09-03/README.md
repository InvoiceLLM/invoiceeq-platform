# Feature 6.1 item C3 / Gap 424 — zero rows is a diagnosis, never an answer

**Date:** 2026-09-03 · **Personas:** senior-dev (build), functional-tester (runs)

| run | engine | command | result |
|---|---|---|---|
| C3 suite | **Postgres** `localhost:5433` | `pytest tests/test_c3_zero_rows_diagnosis.py -p no:randomly -q` | **19 passed in 15.44s** |
| FE contract spec | Playwright (Chromium) | `npx playwright test e2e/chat-attachment-contract.spec.ts` | **17 passed (1.2m)** |
| FE types | tsc | `npx tsc --noEmit` | exit 0 |
| wide regression, 18 suites touching the changed functions | Postgres | `pytest tests/test_chat_sql_quality.py tests/test_rag.py tests/test_telemetry.py tests/test_chat_attachments.py tests/test_chat_doc_content_branch.py tests/test_direction_aware_chat.py tests/test_chat_training.py tests/test_agent_eval_multiturn.py tests/test_a1_generation_budget.py tests/test_a2_fast_deployment.py tests/test_c2_cache_correctness.py tests/test_rag_chunk_provenance.py tests/test_a4_prompt_prefix.py tests/test_dependency_spans.py tests/test_tier3_discovery.py tests/test_chat_progress.py tests/test_online_quality_judge.py tests/test_c3_zero_rows_diagnosis.py -p no:randomly -q` | **572 passed, 5 failed in 144.06s** |
| the 5, after updating each to the new contract | Postgres | targeted re-runs | **4 passed** + **3 passed** (incl. two unchanged siblings) |

## The five, each accounted for

| test | why it failed | what changed |
|---|---|---|
| `test_a_name_lookup_that_genuinely_found_nothing_is_left_alone` | asserted the bare sentinel in the answer | now asserts the ask-back, `needs_confirmation`, no proposed options, and — the original point — no re-search |
| `test_a_zero_result_turn_is_flagged_on_the_sql_summary_event` | expected a `chat.sql_summary` event on a zero-row turn | a diagnosed turn makes no summary call; asserts no summary event, the sentinel absent, and the generation event present |
| `test_attribute_term_block_reaches_both_prompts` | the turn ended in an ask-back so no summary prompt was built | seeds one surfaced row; the test is about a normal turn |
| `test_the_tier_is_additive_the_single_turn_bank_is_untouched` | 35 → 36 golden cases | count updated with the reason |
| `test_query_results_have_exactly_one_blank_line_before_and_after_heading` | **had been passing on a zero-row result** — its dashed tenant literal matches nothing on SQLite, and the heading it checks was appended even to the sentinel | uses both UUID spellings and asserts the seeded row is in the output |

## What this evidence does not show

The three proving cases named in the spec (typo → proposal, mis-routed text →
`vector_answered`, unknown vendor → ask-back) are covered as **unit and Postgres
tests with the vector probe patched**. The live end-to-end of a real typo against
a real tenant with real Chroma is the golden case `zero_result_typo_vendor`, which
runs in the next golden pass — the "before" run for A4 was already in flight on
the pre-C3 code when C3 landed, so this case first appears in the "after" run.
