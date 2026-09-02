# senior-dev — Feature 26 Part 2, task H5 (content branch + intent split)

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_26_chat_attached_documents.md`
(§P2.3A B1/B2/B5/B6, §P2.4 E-1/E-3, §P2.8, §P2.11 H5). Tracker: Gap 378.

- [x] 1. Read spec (P2.3A, E-1, E-3, P2.8) + `_run_attached_document_turn()` + H1–H4 build notes
- [x] 2. `_wrap_retrieved_document_text()` + `_DOCUMENT_TEXT_GUARD_INSTRUCTION` beside `_wrap_user_input`
      (per-span marker pairs, `[Page N]` header, distinct injection log wording)
- [x] 3. B6 one-line fix: `_INJECTION_GUARD_INSTRUCTION` into the comparison branch's prompt
- [x] 4. E-1/B2 deterministic intent split: boundary-anchored keyword alternations,
      `_INTENT_BIAS_BY_DOC_TYPE` (both-match only), clarify on neither-match for every family
- [x] 5. Content branch: already-loaded summary + one `search_attachment_chunks()` + one
      `get_llm()` narration carrying H1's imported marker; empty-search path makes no LLM call
- [x] 6. `attachment_clarification` per §P2.8; 3 new `_PROGRESS_STEPS` names
- [x] 7. `tests/test_chat_doc_content_branch.py` — 33 tests (V-5/6/7/7b/8/10/24-unit/25-unit/25b
      + a real-signature binding test)
- [x] 8. Runs: new file → 33 passed; +attachments/doc-search/progress/queue → 109 passed;
      rag/queries/direction/sql-quality/sse → 222 passed, 1 pre-existing failure (V-19's known one)
- [x] 9. Negative controls, four, all restored green afterwards
- [x] 10. Gap 378 filed in `be_features_tracker.md` (collision re-checked: 376/377 taken mid-run);
      spec H5 `[x]` + additive Built notes under E-1 and E-3

Final status: H5 complete. NOT in scope and not built — H6 (Tier 3), H6b
(`compare_documents`), H7 (async wiring), all FE. V-25's live-model probe is
deliberately not attempted (functional-tester's, task V). Changes left
uncommitted.
