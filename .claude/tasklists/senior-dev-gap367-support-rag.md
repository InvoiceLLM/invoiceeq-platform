# senior-dev — Gap 367: Support Assistant hybrid vector search

Scope approved 2026-09-02 (founder gate). Hybrid vector search only — no LLM call, keyword scoring keeps priority, vector search only fires on a zero-keyword-match query before falling through to the generic miss.

- [x] Read `tests/test_support.py`, `tests/conftest.py`, `config.py` (MOCK_EMBEDDINGS) to confirm test conventions before writing code. Found: `conftest.py`'s `use_ephemeral_chroma` autouse fixture already makes Chroma safe (session-scoped EphemeralClient); `MOCK_EMBEDDINGS` is NOT set globally, each test file opts in itself — `test_support.py` never had to before, so it needed adding.
- [x] Implement `_get_support_collection()` / seeding of the 12 `KNOWLEDGE_TOPICS` into a shared (non-tenant) Chroma collection, reusing `chroma_client.py`'s client/embedding singletons. Placed the vector fallback as step 5, deliberately AFTER error triggers and the human-help check (not before/between the keyword pass), so those two deterministic guarantees are provably unaffected.
- [x] Implement `_vector_match_topic(query)` and wire it into `evaluate_support_query()`.
- [x] Add new tests (`TestSupportAgentVectorFallback`, 5 cases): random-mock-never-false-positives, semantic-match-with-no-keyword-overlap (monkeypatched controlled embeddings), keyword-match-never-reaches-vector-step (call-counter proof), error-trigger-never-reaches-vector-step (call-counter proof), vector-failure-degrades-to-existing-miss.
- [x] Run `tests/test_support.py` in isolation — real pytest run: **75 passed**, 30.21s.
- [x] Run the full backend suite for regression — **25 failed, 1773 passed, 3 skipped, 4 errors, 177.65s**. Checked every failure individually: all pre-existing/environmental (local Postgres missing a migrated `tenant.api_key_scope` column across unrelated `*_on_postgres` tests; the already-documented Gap 354 `test_rag.py` failure; unrelated benchmark-telemetry/ops-workbook/connector tests). Zero failures in `tests/test_support.py`.
- [x] Update `feature_19_support_tickets_and_notifications.md` Task 19.3 with the as-built design + verification.
- [x] Flip Gap 367 to `[x]` in `be_features_tracker.md` with real verification results.

**Final status: done.** Hybrid vector fallback built exactly to approved scope (no LLM call, keyword pass unaffected, vector search only fires on a zero-keyword-match query). `tests/test_support.py` 75/75 passing; full-suite regression confirms no new breakage. Real-model semantic-quality validation (vs. the mechanism being wired correctly) and the 0.35 threshold's live tuning are explicitly left open, not claimed as done.
