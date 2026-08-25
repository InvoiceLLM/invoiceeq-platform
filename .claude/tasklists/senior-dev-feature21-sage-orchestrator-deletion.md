# senior-dev — Feature 21 / SAGE orchestrator deletion (Gap 316)

Decision taken 2026-08-25 after the live-tenant head-to-head (default 23/25, SAGE 19/25,
SAGE-right-where-default-wrong = 0, +87% cost, +90% median latency, leaked-internal-caveats
defect on 5/25 turns). Delete the orchestrator loop; keep the two Feature 6 dependencies.

- [x] 1. Read tracker Feature 21 section + Gap 310/315 entries + `feature_21_sage.md` Phase 3 section
- [x] 2. Caller analysis, function by function, for every public name in `agents/query_tools.py`
      — result: only `get_full_record`/`compute`/`parse_results_table`/`column_index`/
      `is_summable_money_column` have callers outside the orchestrator; the other four tools
      and the whole name-matching layer appear only in comments and prose.
- [x] 3. Caller analysis for `agents/sage_prompts.py` — `PERSONA_BLOCK` live (Gap 313),
      everything else zero callers. File KEPT, dead half flagged in its docstring (Gap 314 precedent).
- [x] 4. Delete `agents/sage_orchestrator.py`
- [x] 5. Remove `ENABLE_AGENTIC_SAGE` from `config.py` + its branch in `agents/query_agent.py`
      (not in `.env.example`; no bicep param ever existed — checked)
- [x] 6. Delete `tests/test_agentic_sage.py`, `tests/agentic_sage_parity_cases.py`,
      `tests/run_agentic_sage_live.py`, `tests/fixtures/query_agent_flag_off_parity.json`
- [x] 7. Delete `tests/realworld_tenant/run_sage_vs_default_live.py` + its output JSON
      — confirmed gitignored (`Prod_Invoice_LLM/.gitignore:109`) and never committed; noted in the Gap.
- [x] 8. Prune `agents/query_tools.py` 1746 → 606 lines; `tests/test_query_tools.py` 89 → 25 tests
- [x] 9. De-SAGE `scripts/run_agent_eval.py` (removed `_ToolBox` wrapper, `_agentic_sage_enabled`,
      `_measure_tool_result`, `_evidence_text`, `AGENT_SAGE_PATH`, 3 dead patch targets)
- [x] 10. Fixed `tests/test_model_substitution.py` (`_CHAT_PATH_MODULES` 3 → 1); telemetry /
      `online_eval_signals.py` left untouched (out of scope) and their now-permanent degeneracy flagged
- [x] 11. Deleted `docs/feature_21_sage.md`; folded closing summary into the tracker's Feature 21 section
- [x] 12. Fixed `application_doc_summary.txt` index entry (26 → 25 files) + `feature_6_rag.md`
      + `feature_20_23_24_ops_workbook.md` + the Gap 285 entry
- [x] 13. Repointed code comments in `query_tools.py`, `sage_prompts.py`, `run_agent_eval.py`,
      `large_invoice_fixture.py`, `sage_seed_fixtures.py`, `agent_eval_golden_sample.py`,
      `benchmarks/__init__.py`, `models.py`
- [x] 14. Filed **Gap 316** in `be_features_tracker.md`
- [x] 15. Narrow run (11 files): **451 passed / 1 failed** — the failure is the known pre-existing
      `test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message`.
      `ruff check` clean on all 12 touched Python files. Full suite deliberately NOT run.
- [x] 16. Repo-wide grep: zero imports of anything deleted, zero flag reads, zero calls to deleted
      functions, zero live doc-links to the three deleted F21 docs.

Final status: **DONE.** One item for the founder, not actionable by an agent: `active-work.md:18`
still says "SAGE Phase 3 — gated on Gap 310's real-world result … (see `feature_21_sage.md`)" and
lists it under "Frozen / do not touch". That gate was satisfied and the decision taken today; the
doc it points at no longer exists. `active-work.md` is founder-owned, so it was left unedited.
