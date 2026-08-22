# senior-dev — Feature 23 Phase 1 (AI Control Tower telemetry)

> **Process note, stated honestly:** CONVENTIONS.md asks for this file *before* work starts,
> updated as each step lands. It was written at completion instead — the run was executed without
> it. The checklist below is the real sequence that ran, not a plan. Flagged rather than
> back-dated.

- [x] Read `.claude/CONVENTIONS.md` and `docs/feature_23_ai_control_tower.md`
- [x] Audit every real LLM call site (`get_llm` grep across `apps/invoice-be`) instead of trusting
      the registry table — found 12 invocation points across 9 functions, plus 2 unregistered ones
- [x] Confirm SENTINEL's named detectors are deterministic regex (no LLM to instrument)
- [x] Confirm `azure-monitor-opentelemetry` already in `pyproject.toml` + `uv.lock` (no
      `requirements.txt` exists; Dockerfiles use `uv sync --frozen`) — no dependency change needed
- [x] Confirm Feature 19 already calls `configure_azure_monitor` in `main.py` and
      `queue_worker/main_worker.py` — reuse, don't initialise a second SDK
- [x] Verify the Azure exporter's `microsoft.custom_event.name` → `customEvents` mapping against
      the installed package source, not from memory
- [x] Verify `register_configure_hook` token capture works against a real LangChain chat model
- [x] Record green baseline: 813 passed / 6 pre-existing failures / 6 skipped
- [x] Write `telemetry.py` (`track_agent_call`, `tracked_llm_call`, `resolve_model_name`, `LlmUsage`)
- [x] Wire extraction (`extract_node`, `dynamic_qa_node`) + `tenant_id` onto `ExtractionState`
- [x] Wire chat (`classify_query`, `run_sql_generation_loop`, SQL summary, RAG, CHAT)
- [x] Wire SAGE (`_plan_node`, `_synthesize_node`, tenant passed via `build_sage_graph` deps)
- [x] Wire trainer/EVOLVE (`refine_constraints`, `_validate_rule_text`, `flag_missed_alert`)
- [x] Add `tests/test_telemetry.py` (5 tests)
- [x] Full suite after: 818 passed / same 6 pre-existing failures / 6 skipped — baseline preserved
- [x] Ruff clean on new code (3 remaining F401s are pre-existing unused typing imports)
- [x] Update `feature_23_ai_control_tower.md` (Phase 1 as-built section, deviations, corrected
      SENTINEL registry row) and `be_features_tracker.md` Feature 23 Phase 1 → `[x]`

**Final status:** Phase 1 code complete and test-verified locally. **Not** verified in Application
Insights — that needs the `APPLICATIONINSIGHTS_CONNECTION_STRING` Container App secret, which is a
founder action and deliberately not done here. Changes left uncommitted.
