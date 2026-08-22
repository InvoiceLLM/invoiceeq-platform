# Feature 21 — live eval of the NEW tool set (identify/get_full_record/search/aggregate)

2026-08-21. Everything left uncommitted.

- [x] Read the existing harness (`services/agent_eval.py`, `scripts/run_agent_eval.py`,
      `tests/agent_eval_golden_sample.py`) and the new tools/orchestrator
- [x] Confirm `get_all_invoice_chunks()` is unbounded (chroma_client.py:483) — confirmed:
      plain `collection.get(where={"invoice_id": ...})`, no limit/threshold, sole caller is
      `get_full_record`
- [x] Large multi-page invoice fixture (`tests/large_invoice_fixture.py`) via
      `tests/e2e/pdf_builder.py` + real fitz page text — LARGE 400 lines / 11 pages / 15.9k tokens,
      SMALL 1 line / 1 page / 242 tokens
- [x] Per-tool-call + per-call-site instrumentation in `scripts/run_agent_eval.py`
- [x] Golden cases `large_invoice_full_detail` / `small_invoice_full_detail`
- [x] LIVE FINDING #1 (fixed): identify prompt never named the table -> `FROM invoices` ->
      every single-invoice lookup failed
- [x] LIVE FINDING #2 (fixed): same record fetched 3x per turn; synthesis rendered all three
- [x] LIVE FINDING #3 (measured, bounded): 11-page page dump = 15,977 tokens; synthesis prompt
      129,818 vs 1,906 for the 1-page control
- [x] LIVE FINDING #4 (reported, not fixed): 3 of 11 questions end in a clarifying question with
      no tool call, both runs, incl. the flagship CGST case
- [x] Round A live run, as-found (11 cases x 2 paths, judged)
- [x] Bound implemented: `bound_document_pages()` + `pages_omitted` disclosure; repeat-call reuse
      in `_act_node` with UUID canonicalisation
- [x] 8 new tests (4 `test_query_tools.py`, 4 `test_agentic_sage.py`) — 89 + 41 pass
- [x] Round B live run (post-fix) + Round C 2-turn A/B confirmation
- [x] `feature_21_architecture.md` B4 rewritten (supersedes the stale table), deviation 3a added,
      Status section rewritten
- [x] `feature_21_rag_faithfulness.md`: "What the first live run changed" section + task list
      (2 closed, 2 new open, Phase 3 -> `[~]`)
- [x] `be_features_tracker.md`: live-run entry, Phase 3 wording, open-decisions list 2 -> 4
- [x] Full suite: **1024 passed / 3 failed / 6 skipped / 1 collection error**. The 3 failures are
      the documented pre-existing ones. The collection error is pre-existing too (two files named
      `run_chat_live_test.py`, both dated Aug 19, both match pytest's `*_test.py` pattern) and
      needs `--continue-on-collection-errors` to run the suite at all today.

Final status: done. Two defects found and fixed, one cost bounded from measurement, two behaviours
reported unfixed. Nothing committed.
