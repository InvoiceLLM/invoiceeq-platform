# senior-dev — Feature 26 Part 2, task H3: `services/chat_document_search.py`

Scope: the standalone search module only. **Not** wired into
`routers/chat_attachments.py` (H4) or `agents/query_agent.py` (H5).

- [x] 1. Read CONVENTIONS.md, spec §P2.4 E-2 (incl. H2's "Built" contract), §P2.5,
      §P2.10 V-1/V-3, §P2.11 H3.
- [x] 2. Read the code it lands on: `chroma_client.py` (`get_chat_doc_collection`,
      `index_invoice_document`, `get_embeddings`), `models.py::ChatAttachment`,
      `routers/chat_attachments.py::_extract_attachment`. Finding: the row
      persists `blob_path` + `extracted_json` and **no raw text**, so the chunk
      text is re-read from the stored PDF with `fitz` (same as
      `index_invoice_document`).
- [x] 3. Write `services/chat_document_search.py` —
      `index_attachment_chunks` / `search_attachment_chunks` /
      `delete_attachment_chunks`. Goes through `get_chat_doc_collection()`;
      `_tenant_collection_name` is not imported at all.
- [x] 4. Write `tests/test_chat_document_search.py` — 11 tests: V-1 (asserted
      from the invoice collection's side, three ways, against a non-empty
      invoice collection), V-3 (`limit` == the scoped doc's page count, so a
      post-hoc filter fails it too), V-4's shape, and the required-`attachment_id`
      signature test (no default / `TypeError` / explicit `None` rejected).
- [x] 5. Run the tests. **11 passed**; with `test_rag.py` + `test_chat_attachments.py`
      → 101 passed, 1 failed (the known pre-existing
      `test_process_crash_during_agent_leaves_no_orphan_user_message`).
      Negative controls run both ways (drop `where=` → only the V-3 test failed;
      write into the invoice collection → 6 failed incl. V-1); file restored and
      re-run green after each. Backend is a **real in-memory chromadb
      `EphemeralClient`** (`tests/conftest.py`, Gap 245) — not the
      `PersistentClient` fallback H2 assumed, and not a Chroma server.
- [x] 6. Tracker Gap entry filed. **Collision hit and handled**: written as 372,
      but a parallel Feature 27 build (task G3b) filed 372 on disk while this was
      in progress — renumbered to **Gap 373** and moved after theirs. Tracker
      diff is 92 insertions / **0 deletions**.
- [x] 7. Spec updated: H3 `[x]` in §P2.11 + an additive
      "Built — 2026-09-02, task H3, Gap 373" subsection under E-2, beneath H2's.

Final status: **complete.** Gap 373 filed, everything left uncommitted. H4 (embed
step + `chunk_count`/`indexed_at`/`expires_at`) and H5 (content branch) are the
next tasks; nothing calls this module until they land.
