# senior-dev — Feature 26 Part 2: the feature flag H5 shipped without

Founder-caught defect in H5's original delivery (Gap 378): the intent-split /
clarifying-turn / content-branch logic went live with **no `ENABLE_*` gate at
all**, breaking this repo's own convention that every new capability defaults
`False` and gates its own code path. The founder's original brief asked for an
`FF_GENERIC_DOC_CHAT`-style flag; it was dropped during spec-writing and nobody
caught it, including H5's own dispatch.

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_26_chat_attached_documents.md`
§P2.4 E-1 / E-3 (both "Built — task H5" notes), §P2.11 H5.

- [x] 1. Read `_run_attached_document_turn()` in full + H5's build notes + Part 1's
      original (pre-H5) single-branch behaviour, and Feature 27 E3's flag-OFF rigour
- [x] 2. `config.py` — `ENABLE_GENERIC_DOC_CHAT: bool = False` (L256), house docstring
      style, with the flag-OFF == Part-1 guarantee and the four flip criteria stated
- [x] 3. Gate H5's entry point — verified at `agents/query_agent.py` L3198: flag OFF
      genuinely never calls `_classify_attachment_intent()`, so
      `_run_attachment_content_branch()` has no caller. A different path, not a
      branch that happens not to fire.
- [x] 4. Tests — autouse flag-ON fixture for H5's existing set; **6 flag-OFF parity
      tests** added, including the load-bearing `assert_not_called()` on the
      classifier and the paired ON/OFF run over an identical setup
- [ ] 5. Run the suites — **NOT DONE. No run result is recorded for any of them.**
- [x] 6. Gap entry in `be_features_tracker.md` — filed retroactively 2026-09-02 by
      the Wave 0 doc-reconciliation pass as **BE Gap 382** (repo-wide max was 380;
      381 went to Feature 27 G9/G10/G14 in the same pass), not by this dispatch
- [x] 7. Spec doc — two additive "Correction — BE Gap 382" subsections in
      `feature_26_chat_attached_documents.md`, one beside E-1's H5 build note and
      one beside E-3's, per hard rule 4. Nothing rewritten.

**Open, found while filing:** the flag work's own code comments carry a **stale
provisional gap number** — `agents/query_agent.py` L3180 says "Part 2's safety gate
(Gap 380)" and `tests/test_chat_doc_content_branch.py` has two "Gap 380" section
comments. **380 is FE Gap 380 (Feature 26 task H11); this work is BE Gap 382.** Not
corrected, because the pass that found it was documentation-only and `.py` edits were
out of scope. One-line comment fix in each file is the follow-up.

Final status: **code complete, unverified (no test run recorded), gap filed
retroactively as BE Gap 382 (2026-09-02).** Item 5 and the stale in-code gap number
are genuinely outstanding.

Out of scope, do not touch: H10/H11/H12 FE work (composer, message rendering,
`useChatSession` wiring) — may still be landing in parallel this session.
