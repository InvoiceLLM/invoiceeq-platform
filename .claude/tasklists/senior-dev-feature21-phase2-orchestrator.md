# Feature 21 Phase 2 — orchestrator loop (senior-dev)

- [ ] Read CONVENTIONS, feature_21 spec, query_tools.py, query_agent.py (Phase 1 refactor), extraction_agent.py LangGraph precedent
- [ ] Confirm environment: LLM reachable, DB/docker state, langgraph version
- [ ] Capture pre-change parity golden (scripted cases through today's `run_query_agent()`) BEFORE editing anything
- [ ] `config.py`: add `ENABLE_AGENTIC_SAGE: bool = False`
- [ ] `agents/sage_orchestrator.py`: LangGraph loop, 4 tools bound with tenant/db in closure, call cap, clarification short-circuit, compute-backed synthesis
- [ ] `agents/query_agent.py`: flag-guarded route at top of `run_query_agent()`, nothing else touched
- [ ] `tests/test_agentic_sage.py`: mocked mechanics tests (cap, short-circuit, wiring, compute-grounding)
- [ ] Parity test: flag-off outputs byte-identical to the pre-change golden
- [ ] Update Phase 1's AST boundary test in `test_query_tools.py` to its Phase 2 form (flag-guarded only)
- [ ] Real-LLM run: Titan Steel / Redwood ambiguous-direction + other historical phrasings; record actual transcripts
- [ ] Run full BE suite deltas (test_query_tools, test_chat_sql_quality, test_rag, adjacent)
- [ ] Docs: feature_21_rag_faithfulness.md "Phase 2: what actually shipped" + tracker line
