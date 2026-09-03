# senior-dev — Feature 26 Part 2, task H4 (embed step + E-6 columns)

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_26_chat_attached_documents.md`
(§P2.4 E-6/E-7, §P2.5 `routers/chat_attachments.py` row, §P2.11 H4).
Scope: migration + 3 columns + wiring `index_attachment_chunks()` into the upload
path + the one `CHAT_ATTACHMENT_TTL_DAYS` config knob + chunk cleanup on the
existing row-deletion path. **Not** the sweeper script (H8), **not** the content
branch (H5), **not** the async queue (H7).

- [x] Read spec §P2.5/E-6/E-7 + H2/H3 build notes; read the real code
- [x] Verify current alembic head — walked every revision/down_revision pair:
      `c2d3e4f5a6b7` still the single head, so the spec's citation held
- [x] Locate every existing `ChatAttachment` row-deletion path — **there is no
      attachment-delete endpoint**; the two places are `routers/chat.py::delete_session()`
      and `scripts/sweep_sandbox_tenants.py::_purge_sandbox()`, both of which
      deleted the parent session and left the FK child behind
- [x] `config.py` — `CHAT_ATTACHMENT_TTL_DAYS: int = 30`
- [x] `models.py::ChatAttachment` — `chunk_count`, `indexed_at`, `expires_at`
- [x] New Alembic migration `d3e4f5a6b7c8_add_chat_attachment_index_columns.py`
- [x] `routers/chat_attachments.py` — `expires_at` stamped at creation; new
      `_index_attachment()` called only on `EXTRACTED`; failure logs at ERROR and
      leaves `chunk_count=0`/`indexed_at=None`, never fails the upload
- [x] Chunk cleanup + row deletion on both existing delete paths
- [x] Tests — 5 in `tests/test_chat_attachments.py`, all through the real upload
      endpoint (real Chroma, local blob, stubbed OCR/extraction)
- [x] File → 33 passed; `test_chat_document_search.py` + `test_chat_queue.py` +
      `test_chat_progress.py` + `test_sandbox_keys.py` → 95 passed
- [x] Negative controls: embed call removed → 2 failed; delete cleanup removed →
      1 failed; both restored and re-run green
- [x] Migration verified against real Postgres 16.15 — upgrade, column
      introspection, downgrade (all three gone), upgrade again
- [x] Gap 374 filed (collision-checked immediately before writing: max was 373)
      + spec H4 `[x]` with a Built note under E-6, additive

**Final status: complete.** H4 is done; nothing here builds H5's content branch,
H7's async wiring or H8's sweeper script. Changes left uncommitted.
