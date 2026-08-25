# Gap 310 — full invoice record on the default chat route

Founder instruction: "give the pdf invoice sql whole row as tool to LLM", corrected
mid-run to be **generic** (any question, not tax-keyword-gated).

- [x] 1. Read query_agent.py / query_tools.py / models.py / handlers.py, confirm the gap
- [x] 2. Decide mechanism (deterministic fetch vs. LLM tool-binding) and record why
      — deterministic; an LLM tool-call costs a whole extra generation to decide a
      `db_session.get()` on a primary key.
- [x] 3. `query_tools.get_full_record()` — add `include_document_pages` so the default
      route can reuse it without the Chroma page dump
- [x] 4. `query_agent` — `_full_record_block_for()` + wire into the SQL route's summary
      prompt, after the Gap 231 companion-query id harvest (the harvest moved ABOVE
      the prompt build, or the block would be empty on exactly the detail questions)
- [x] 5. Seed `taxes` in `benchmarks/sage_seed_fixtures.py` (Rajesh Steel CGST/SGST)
      — CGST 9% 9,000 + SGST 9% 9,000 = the 18,000 already in `tax_amount`; `taxes`
      defaulted to `"[]"` in `_ROW_DEFAULTS` for every other row.
- [x] 6. Rewrite `rajesh_steel_cgst` golden case to expect the real breakdown
      — was a decline ("no per-component breakdown exists"), now INR 9,000.00, with
      the rubric still forbidding a derived/halved figure.
- [x] 7. `benchmarks/region_seed_fixtures.py` — obsolete "schema limitation" rationale
      struck through (not deleted) and corrected: it was a prompt limitation, never
      a schema one.
- [x] 8. Tests: real answer, tenant isolation, fail-soft, bounded, not keyword-gated
      — 8 tests in `tests/test_chat_sql_quality.py -k full_record`. Six already
      existed; the two added on 2026-08-25 close the character-budget half of
      "bounded": `test_full_record_block_is_bounded_by_its_character_budget`
      (surplus held back AND the count disclosed) and
      `test_full_record_block_still_shows_one_record_larger_than_the_whole_budget`
      (the deliberate first-record exception). 8 passed.
- [x] 9. Full suite `uv run pytest tests/test_*.py -p no:randomly -q` — the "1443"
      baseline was stale; measured today: before **1381 passed / 3 failed / 7
      skipped**, after **1383 passed / 3 failed / 7 skipped**. Same 3 pre-existing
      failures (2x `test_connectors.py` needs a local Redis, 1x `test_rag.py` calls
      `post_chat_message()` without `background_tasks`) — nothing new broke.
- [x] 10. `ruff check` — clean on `tests/test_chat_sql_quality.py`,
      `agents/query_agent.py`, `agents/query_tools.py`,
      `benchmarks/sage_seed_fixtures.py`, `benchmarks/agent_eval_golden_sample.py`,
      `benchmarks/region_seed_fixtures.py`.
- [x] 11. Docs: **Gap 310 entry filed in `be_features_tracker.md`** (none existed —
      `f985ee9` left only forward references from the Feature 21 and 2026-08-21
      defect entries; the latter now records that Gap 310 closes it). Spec body went
      into **`docs/feature_6_rag.md`** — "Recent Fix (Aug 24–25, 2026) — Gap 310"
      plus File Coordinates and a Verification Plan bullet — rather than
      `feature_21_sage.md`, which already carries an accurate Gap 310 paragraph and
      is out of scope for this pass; the change is Feature 6's default route, not
      SAGE's.

Status: done — code + fixtures + tests + docs complete. **Not** covered: a live
`scripts/run_agent_eval.py` re-run of the rewritten `rajesh_steel_cgst` case, so the
new expectation has mocked-mechanics evidence only. That live result is the stated
blocking condition on SAGE Phase 3.
