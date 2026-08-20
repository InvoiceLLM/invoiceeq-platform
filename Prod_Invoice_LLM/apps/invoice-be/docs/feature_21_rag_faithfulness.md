# Feature 21: RAG Faithfulness & Retrieval Quality

**Phase 1 built 2026-08-20** (1a/1b/1c — see "Phase 1: what actually shipped" below). Phases 2 and 3 are still target design only. Extends [feature_6_rag.md](feature_6_rag.md) (SAGE's RAG/SQL/CHAT routing agent) rather than replacing any of it; nothing here changes the SQL-generation or routing logic those routes already own.

## Why this exists

A 2026-08-20 architect review, informed by a general RAG-engineering reference (not this codebase specifically) and cross-checked line-by-line against SAGE's actual prompts (`agents/query_agent.py`), found several concrete, currently-real gaps: no explicit anti-hallucination instruction in the RAG/summary prompts, RAG's retrieved chunks are used in whatever order ChromaDB returns them (no reordering against the well-documented "lost in the middle" effect), a zero-result query gets reported as a flat dead end instead of a grounded next step, and there is no automated faithfulness/quality evaluation loop at all — every defect this session was caught by manual live testing, never a regression harness.

Several adjacent ideas from that same review (a cross-encoder reranker model, hard per-chunk token budgeting, an LLM-Lingua-style compression pipeline) were considered and explicitly rejected for this feature: they solve problems of scale (dozens of chunks, large contexts) that SAGE does not have today at a 5-chunk retrieval size. They're recorded under **Deferred, not in scope** below so the reasoning isn't lost, not silently dropped.

## File Coordinates (planned)

* `agents/query_agent.py` — **Phase 1 landed here 2026-08-20**: constants `_RAG_FAITHFULNESS_MANDATE` / `_SQL_SUMMARY_FAITHFULNESS_MANDATE` (injected into the RAG prompt and the SQL summary prompt respectively), `_reorder_chunks_for_context()` (called between `query_invoice_chunks()` and the `context_str` build in `run_query_agent()`'s RAG route), and `_validate_citations()` (called after that route's `llm.invoke()`, alongside the existing Gap 239 existence check).
* `agents/query_agent.py` (Phase 2) — a new near-match/broaden-search fallback, wired into the SQL route's zero-row branch in `execute_generated_sql()`'s caller and an equivalent empty-chunk branch in the RAG route. Likely a new small module (`services/query_fallback.py` or similar — final placement decided at implementation time) rather than growing `query_agent.py` further.
* `tests/test_rag.py` — Phase 1's coverage landed here (9 tests, listed under Verification Plan below), including the SQL-summary mandate assertion; `tests/test_chat_sql_quality.py` was left untouched (it already runs green against the amended summary prompt, 71 passed / 5 Postgres-only skips) and stays the home for Phase 2's SQL zero-row fallback tests.
* `tests/benchmark/` (Phase 3) — RAGAS faithfulness metrics integrated into the existing Tier 2 benchmark harness ([feature_13_test_benchmark_suite.md](feature_13_test_benchmark_suite.md)), not a new harness.

## Functionality (target)

**Faithfulness mandate**: the RAG and SQL-summary prompts gain explicit grounding language — "Answer only using the provided context blocks" / "never speculate beyond context" — so an answer with no real backing in the retrieved chunks or query results says so, rather than the model filling the gap plausibly.

**Chunk reordering**: ChromaDB's top-5 RAG results already carry a similarity score; before they're concatenated into `context_str`, reorder them so the single most relevant chunk is first and the second-most relevant is last — exploiting primacy/recency bias against the middle-of-context degradation effect. No new model or dependency; a sort against a score already computed.

**Citation-claim validator**: a post-processing check on the RAG route's generated answer, confirming its citation list is well-formed and consistent with what Gap 239's existence-check already allows through — closing the gap between "citations point at real invoices" (already true) and "the citations actually back the claims made in the prose" (not yet checked).

**Near-match fallback skill** (Phase 2): when the SQL route's primary query returns zero rows on a named-entity or category filter, or the RAG route's retrieval returns no chunks above a relevance floor, run one cheap, deterministic broader query (nearby vendor/customer names; a looser category check) before answering, and hand those candidates to the summary/RAG prompt so a dead end becomes "I didn't find X, did you mean one of these" instead of a flat refusal. Mirrors the one fallback pattern that already exists (`_find_invoice_number_candidate()`), generalized past its current invoice-number-only scope.

**RAGAS evaluation** (Phase 3): faithfulness scoring added to the existing Tier 2 benchmark run, giving this feature (and every future prompt change to SAGE) a real automated signal instead of relying on live manual testing to catch regressions.

## Phase 1: what actually shipped (2026-08-20)

All three pieces are in `agents/query_agent.py`. Nothing in `chroma_client.py`, the SQL-generation rules, or `classify_query()` was touched.

**1a — faithfulness mandate.** Two module-level constants rather than inline prompt text, for the same reason Gap 237's directives are constants: the tests assert against the exact strings the prompts actually carry, so the two can't drift.
- `_RAG_FAITHFULNESS_MANDATE` sits in the RAG system prompt directly under the "Answer in 1-3 sentences" line. It requires every figure/date/vendor/invoice number/status to appear in one of the context chunks, forbids filling a gap from general knowledge, and makes "not found in the documents I can see" an explicitly correct answer. One addition beyond the spec's wording, made after reading what the prompt actually contains: it states that the tenant-statistics snapshot and the business-rules block below it are *orientation and interpretation, not document content*, so they can't be treated as the source of a cited figure. Those two blocks are injected into the same prompt (Task 6.14, Gap 48), so a bare "answer only from the context" would have been ambiguous about them.
- `_SQL_SUMMARY_FAITHFULNESS_MANDATE` sits near the top of the SQL summary prompt, before the line-item formatting rules. Adapted to that prompt's actual job — summarize only the returned rows, never add trends/context/totals the rows don't support, never carry a number over from earlier in the conversation as if this query returned it, say "no matching records" plainly on an empty result. It explicitly carves out the one arithmetic the prompt already demands (the per-currency line-item totalling added 2026-08-19), so the mandate can't be read as forbidding it.
- The CHAT route was deliberately left alone: it has no retrieved context to be faithful to, and it already got its own scope boundary on 2026-08-19.

**1b — chunk reordering.** `_reorder_chunks_for_context(chunks)` returns `[chunks[0], *chunks[2:], chunks[1]]` — ranks 1..5 become 1, 3, 4, 5, 2. Fewer than 3 chunks is returned unchanged (with 2, best-first/second-best-last is already true). Two decisions worth recording because the spec's own description was slightly off:
- **Rank is list position, not a re-sort on a score.** The spec said "a sort against a score already computed." `query_invoice_chunks()` does compute one, but `combined_score` (cosine distance *minus* the keyword boost) is used for its internal sort and then **not** included in the returned dicts — the returned per-chunk fields are `id`, `document`, `metadata`, `distance`, `keyword_score`, `matched_by`. Since the function already returns best-first in that hybrid order, the reorder takes list position as the rank. Re-sorting on the returned `distance` was considered and rejected: it would discard the keyword half of Task 6.8's hybrid rank and silently demote every chunk admitted by the keyword channel, which is a retrieval-behaviour change, not a reordering.
- **Citations are still built from the original rank order**, not the reordered one. The reordering is about where the model reads text; the citation list is what the user sees, and there's no reason to show them their second-best source last.

**1c — citation validator.** `_validate_citations(citations)` returns a list of human-readable problems (empty when clean) and is called in the RAG route right after `llm.invoke()` succeeds, before the citation links are rendered. The caller logs one WARNING naming every defect and continues. Scope, after reading Gap 239's existing check rather than assuming from the spec: Gap 239 already guarantees each surviving `invoice_id` resolves to a real tenant-scoped `Invoice` row, and its filter incidentally drops any citation with a null/unparseable id too — so the gap it leaves is the *rest* of the payload. A chunk whose metadata is missing `page` or `vendor_name` still renders as `[Source: None (Page None)]`, which reads to a user exactly like a fabricated citation. The validator checks id presence + UUID shape, page presence + positive-integer shape, vendor-name presence, and that each entry is a mapping at all.
- **Warn-only, on purpose.** The invoice genuinely exists; dropping the link would cost the user a working source over a cosmetic metadata defect. The call is also wrapped in its own `try/except` so the check can never break an otherwise-successful answer.
- **Deliberately not semantic.** It says nothing about whether the prose actually rests on the cited page — that needs Phase 3's RAGAS work and is out of scope.

## Phase 2: implementation status (2026-08-20 — COMPLETE)

Phase 2 is fully implemented and test-verified. It adds no new model or dependency and leaves route classification, SQL generation, indexing, tenant isolation, cache keys, normal successful paths, and Chroma's relevance threshold unchanged.

- SQL: after the existing exact invoice-number fallback fails, a deterministic helper accepts only an explicit vendor/customer/category phrase. It performs one capped, tenant-scoped lookup across the direction-aware counterparty columns plus the existing tags/items fields, excluding soft-deleted rows. Candidates are supplied only as a `POSSIBLE NEAR MATCHES` block whose summary instruction requires a hedged "Did you mean …?" question; they never replace the original no-result table.
- RAG: only an empty first retrieval gets one retry using that explicit phrase. It calls the same tenant-scoped `query_invoice_chunks()` function and therefore retains the existing relevance gate. Any returned context is labelled a possible, non-exact match; another empty result keeps the normal no-document outcome.
- **Coverage (2026-08-20): 6 Phase 2 tests, all passing:**
  - `tests/test_rag.py`: `test_broadened_search_phrase_only_accepts_explicit_entity_or_category` (3 parametrized cases), `test_rag_empty_result_uses_one_broader_lookup_and_hedges_it`, `test_rag_nonempty_result_does_not_retry_broader_lookup` — 5 tests.
  - `tests/test_chat_sql_quality.py`: `test_sql_zero_row_near_match_is_only_a_hedged_clarification` — 1 test.
- **Still outstanding:** live tenant spot-check (a real RAG/SQL miss against the production stack to confirm the hedged "Did you mean?" surfaces correctly end-to-end).

## Explicitly out of scope for this feature

- Routing/classification logic (`classify_query()`) — untouched.
- SQL generation rules (rules 1–11, including 6d) — untouched. This feature is about retrieval/grounding quality and evaluation, not query correctness, which is its own well-developed area with its own incident history.
- Any change to what gets embedded/stored in ChromaDB (`chroma_client.py`) — retrieval quality here is about ordering and fallback, not indexing.

## Deferred, not in scope — recorded, not dropped

- **Cross-encoder reranker model** — real technique, weak fit at a 5-chunk retrieval size; revisit if RAG answer quality is shown to suffer from chunk ordering after the free reordering step above, or if chunk count grows materially.
- **Adaptive per-chunk token budgeting** — low priority at current prompt sizes; the "dynamic top-K by query complexity" half folds naturally into the near-match fallback skill (Phase 2) rather than needing its own project.
- **LLM-Lingua-style context compression** — solves a large-context problem SAGE doesn't have at 5 short invoice-page chunks; revisit only if chunk volume grows enough to matter.
- **Internal (hidden) Chain-of-Thought scaffolding for ambiguous/multi-hop questions** — a real, promising idea (it targets the same reasoning-failure class as rules 4a/6b-vs-6d/9's incident history), but a bigger architectural bet than this feature should carry in one pass. Compatible with the existing "don't show your reasoning to the user" rule (CoT can be internal-only) — worth its own feature once Phases 1–3 here are done and there's a RAGAS baseline to measure it against.

## Tasks

- [x] **Phase 1a** — faithfulness mandate added to RAG and SQL-summary prompts. *(2026-08-20 — `_RAG_FAITHFULNESS_MANDATE`, `_SQL_SUMMARY_FAITHFULNESS_MANDATE`.)*
- [x] **Phase 1b** — chunk reordering (best-first, second-best-last) in the RAG route. *(2026-08-20 — `_reorder_chunks_for_context()`, ranks 1..5 → 1, 3, 4, 5, 2.)*
- [x] **Phase 1c** — citation-claim validator for the RAG route's generated answer. *(2026-08-20 — `_validate_citations()`, warn-only format/consistency check; the semantic "does the prose match the citation" half stays with Phase 3.)*
- [x] **Phase 2** — near-match/broaden-search fallback skill, wired into both the SQL route's zero-row case and RAG's empty/weak-retrieval case. *(2026-08-20 — 6 tests passing across `test_rag.py` and `test_chat_sql_quality.py`; live spot-check still outstanding.)*
- [ ] **Phase 3** — RAGAS faithfulness metric integrated into the existing Tier 2 benchmark suite.

## Verification Plan

- Phase 1 — **done 2026-08-20, except the live spot-check.** 9 tests added to `tests/test_rag.py`: reorder position against 5 ranked chunks (asserting rank 1 first and rank 2 last by identity, nothing dropped/duplicated, input not mutated), the 0/1/2-chunk no-op cases (parametrized), a route-level run asserting the *prompt actually sent* carries the chunks in 1-3-4-5-2 order while `citations` stays in rank order, `_RAG_FAITHFULNESS_MANDATE` present in that same prompt, `_SQL_SUMMARY_FAITHFULNESS_MANDATE` present in the SQL route's summary prompt, a `_validate_citations()` unit test naming every defect class (missing page, non-UUID id, page 0, blank vendor, missing id, non-mapping entry) and confirming a well-formed citation is never reported, and a route-level test that a `page`-less chunk logs `Malformed RAG citation` while the answer and its citation still ship.
  - **Counts:** `tests/test_rag.py` **64 passed, 0 failed** (55 before this work). Regression on everything else that touches `query_agent.py`: `test_chat_sql_quality.py` 71 passed / 5 skipped (the Postgres-only cases, no `DATABASE_URL` pointed at one), and `test_chat_training.py` + `test_direction_aware_chat.py` + `test_rule_schema.py` + `test_trainer.py` 120 passed.
  - **Negative control run**, so the reorder tests can't be passing vacuously: `_reorder_chunks_for_context()` was temporarily stubbed to a no-op and both reorder tests failed (`At index 1 diff: 2 != 3`), then the stub was reverted.
  - **Still outstanding:** the live spot-check against a real tenant's RAG questions. These tests are structural — `test_rag.py` forces `MOCK_EMBEDDINGS=true` at import, so they prove the mandate reaches the prompt and the chunks are placed where the reordering says, never that answer quality improved. Whether the mandate changes model behaviour is exactly the question Phase 3's RAGAS scoring exists to answer.
- Phase 2: **done 2026-08-20.** 6 tests added/verified across `test_rag.py` (5) and `test_chat_sql_quality.py` (1). Covers explicit-phrase extraction (3 parametrized cases), RAG broader-retry with hedged notice, generic-query no-retry gate, and SQL zero-row near-match as suggestion-only. 
  - **Full Regression Pass:** All `query_agent.py`-related test suites run and verify successfully: `tests/test_rag.py`, `tests/test_chat_sql_quality.py`, `tests/test_chat_training.py`, `tests/test_direction_aware_chat.py`, `tests/test_rule_schema.py`, and `tests/test_trainer.py` — **261 passed, 5 skipped**. Live spot-check is still outstanding.
- Phase 3: RAGAS faithfulness score becomes a tracked figure in the Tier 2 benchmark's existing pass-rate reporting, establishing a baseline before any further prompt changes to SAGE are made.
