# Gap 310 — full invoice record on the default chat route

Founder instruction: "give the pdf invoice sql whole row as tool to LLM", corrected
mid-run to be **generic** (any question, not tax-keyword-gated).

- [ ] 1. Read query_agent.py / query_tools.py / models.py / handlers.py, confirm the gap
- [ ] 2. Decide mechanism (deterministic fetch vs. LLM tool-binding) and record why
- [ ] 3. `query_tools.get_full_record()` — add `include_document_pages` so the default
      route can reuse it without the Chroma page dump
- [ ] 4. `query_agent` — `_full_record_block_for()` + wire into the SQL route's summary
      prompt, after the Gap 231 companion-query id harvest
- [ ] 5. Seed `taxes` in `benchmarks/sage_seed_fixtures.py` (Rajesh Steel CGST/SGST)
- [ ] 6. Rewrite `rajesh_steel_cgst` golden case to expect the real breakdown
- [ ] 7. `benchmarks/region_seed_fixtures.py` — obsolete "schema limitation" rationale
- [ ] 8. Tests: real answer, tenant isolation, fail-soft, bounded, not keyword-gated
- [ ] 9. Full suite `uv run pytest tests/test_*.py -p no:randomly -q` vs. 1443 baseline
- [ ] 10. `ruff check` every touched file
- [ ] 11. Docs: Gap 310 in be_features_tracker.md + feature_21_rag_faithfulness.md body

Status: in progress
