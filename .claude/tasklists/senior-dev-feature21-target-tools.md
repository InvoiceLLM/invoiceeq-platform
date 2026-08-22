# senior-dev — Feature 21 target tool set (identify / get_full_record / search / aggregate + persona)

Scope: replace `query_invoices` with the target architecture from
`feature_21_rag_faithfulness.md` + `feature_21_architecture.md`. Code-only, stays behind
`ENABLE_AGENTIC_SAGE` (default off, untouched).

- [x] Baseline: full suite before any change — **837 passed / 6 failed / 6 skipped** (matches the
      stated baseline; 3 of the 6 failures were stale assertions inside `test_agentic_sage.py`)
- [x] `agents/sage_prompts.py` (new): `PERSONA_BLOCK`, `IDENTIFY_SCHEMA_BLOCK`, `IDENTIFY_RULES_BLOCK`,
      `AGGREGATE_RULES_BLOCK` + builders, composed from named constants (never one literal), with the
      aggregate schema and rule 4 column list reflected off the live `Invoice` model
- [x] `chroma_client.get_all_invoice_chunks()` — direct metadata filter, every chunk for one invoice
- [x] `query_tools.identify_invoices()` — narrow 6-column lookup + deterministic normalized/fuzzy
      name matching + per-phrase ambiguity -> clarification
- [x] `query_tools.get_full_record()` — full ORM row (`model_dump`) + every Chroma chunk; five
      storage-plumbing columns omitted and reported in `columns_omitted`
- [x] `query_tools.search_invoices()` — rename/adapt of `search_documents`, hybrid semantic +
      structured (LLM extracts phrases, code builds the SQL)
- [x] `query_tools.aggregate()` — reflected category-match OR clause (minus `addresses` + 5 named
      non-business blobs), currency verification by companion query, zero-result/zero-total statuses,
      provenance via `_harvest_invoice_ids_via_companion_query`, calendar-year assumption note
- [x] `run_sql_generation_loop(telemetry_agent_name=...)` so `sage.identify`/`sage.aggregate` emit
      their own event instead of nesting inside `chat.sql_generation`
- [x] `sage_orchestrator`: six tool schemas, `_ToolBox.dispatch`, planner prompt, `planner_view`,
      per-tool synthesis sections, `PERSONA_BLOCK` in both planner and synthesis prompts
- [x] Tests: `test_query_tools.py` rewritten (84 passed), `test_agentic_sage.py` rewritten (37 passed)
- [x] Full suite re-run: **888 passed / 3 failed / 6 skipped** — 3 pre-existing failures fixed (all
      test-side capitalisation mismatches in `test_agentic_sage.py`), 3 pre-existing failures
      untouched (2 × Redis-dependent `test_connectors.py`, 1 × `test_rag.py` signature drift)
- [x] Updated both Feature 21 docs' task lists + `be_features_tracker.md`, including the nine
      flagged deviations and the two still-open decisions

Final status: built, uncommitted, inert behind `ENABLE_AGENTIC_SAGE` (default False, untouched).
Everything is mocked at the LLM boundary — Phase 3 (real-model regression + live tenant run) is
still not started, and no default-on decision should rest on this evidence.
