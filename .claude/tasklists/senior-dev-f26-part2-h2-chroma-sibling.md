# senior-dev — Feature 26 Part 2, task H2 (Chroma sibling collection + migrate-script fix)

Scope: `chroma_client.py` collection-naming/creation primitive for `chat_docs_{tenant_id}`
(E-2), the full `_tenant_collection_name()` call-site audit, and the
`scripts/migrate_chroma_to_per_tenant.py:67` metadata fix. **Not** H3
(`services/chat_document_search.py`), **not** H4 (embed step).

- [x] Read CONVENTIONS.md, active-work.md, in-flight tasklists (overlap check) — no overlap; the only concurrent BE work touching this area is Track B chat progress (`routers/chat.py`), which does not touch Chroma
- [x] Read spec §P2.4 E-2, §P2.5, §P2.11 H2, V-1/V-2
- [x] Read `chroma_client.py` in full; `_tenant_collection_name()` at L330 (spec citation still correct), `_collection_metadata()` at L84
- [x] Call-site audit: 5 inside `chroma_client.py` (L477/500/518/548/592) all still invoice-only and all still passing `_collection_metadata()`; 3 outside — reembed L107 (read-only), L171 (name for logging; real create at L218 has metadata), migrate L67 (**the defect**)
- [x] Build `_chat_doc_collection_name()` (L340) + `get_chat_doc_collection()` (L361), the single creation site, passing `_collection_metadata()`
- [x] Fix `scripts/migrate_chroma_to_per_tenant.py:67` — passes `_collection_metadata()`, with the limit of the fix written at the call site
- [x] Tests: 4 in `tests/test_rag.py` — name shape, `hnsw:space == "cosine"` on a fresh `chat_docs_*` (V-2), invoice-index does not write into the sibling, migrate script metadata via a recording fake client
- [x] Ran `pytest tests/test_rag.py -k "chat_doc or cosine or migration"` → 7 passed; negative control (metadata stripped from both sites) failed exactly the 2 defect-shaped tests, then restored. Full file 62 passed / 1 **pre-existing** failure (`post_chat_message()` `background_tasks`, from a concurrent change; confirmed against the committed test file)
- [x] Filed BE tracker **Gap 370** (collision-checked immediately before writing: repo-wide max was 369)
- [x] Spec updated: §P2.11 H2 `[x]` + additive "Built — 2026-09-02, task H2, Gap 370" under E-2
- [x] Left uncommitted

Final status: **complete.** H2 delivered as the primitive only — `services/chat_document_search.py` (H3) and the embed step (H4) are untouched, and V-1/V-3/V-4 remain open because no write path exists yet. One finding recorded for H8: `reembed_chroma_collections.py`'s `invoice_chunks_` prefix scan means orphaned `chat_docs_*` collections are cleaned up by nothing today.
