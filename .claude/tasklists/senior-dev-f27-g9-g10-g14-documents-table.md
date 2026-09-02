# senior-dev — Feature 27 G9/G10/G14: `documents` table, sibling collection, list endpoint

Scope approved by founder. E10 + A4/F1 + A4/F2. Parallel dispatch G7 owns
`verify_field_confidence` gating and the tax-backfill gating — do not touch those.

- [x] 1. Read E10 / §2A A3+A4 / §3 build notes / §4 rows (models, alembic, chroma_client)
- [x] 2. Read real code: models.py, chroma_client.py, handlers.py persistence, billing_quota.py,
      chat_attachments.py `_require_owned_attachment`, main.py, alembic head chain
- [x] 3. Collision-check the current max BE gap number
- [x] 4. `models.py` — `Invoice.doc_type` / `Invoice.doc_type_evidence` + new `Document` model
- [x] 5. One Alembic migration (2 invoice columns + `documents` table), real current head
      — `e4f5a6b7c8d9`, `down_revision = d3e4f5a6b7c8` (§4's cited `c2d3e4f5a6b7` was stale).
      **Never applied to any Postgres instance — up/down unproven.**
- [x] 6. `chroma_client.py` — `_document_collection_name()` + `index_document_chunks()`, `_collection_metadata()`
- [x] 7. `queue_worker/handlers.py` — non-INVOICE routing: write `documents` row + delete placeholder
      `invoice` row in one transaction (tenant_id from the loaded Invoice row; delete by id+tenant_id)
- [x] 8. `services/billing_quota.py` — dedup union, tenant predicate on BOTH sides
- [x] 9. `routers/documents.py` — list + detail via `_require_owned_document`; register in main.py
- [x] 10. `tests/test_documents_table.py` — T-E10-1..5 (21 test functions, Postgres-gated
      via `pg_engine_or_skip()`, no SQLite fallback)
- [ ] 11. Run the new tests — **NOT DONE. No run of `tests/test_documents_table.py` is
      recorded anywhere in the repo.** The suite skips without a real Postgres, so a
      skip is not evidence either. Left open deliberately.
- [ ] 12. Regression run over G1–G5/G7 touched suites — **NOT DONE by this task.**
      Gap 379's own sweeps ran other suites *with* G9 present (407 / 118 / 189+1skip /
      168+1 known-failing), which shows G9 did not break them, not that G9 works.
- [x] 13. File the Gap entry in `be_features_tracker.md`; update G9/G10/G14 checkboxes + build note
      — done retroactively 2026-09-02 by the Wave 0 doc-reconciliation pass, not by this
      dispatch. That is the no-code-without-gap rule broken; it is recorded in the entry.

**Also not done, and now an open item on the Gap 381 entry:** §2A/A4/F5's *required*
ruling. `routers/invoices.py` is unmodified, so the ingestion door still dedups on
`Invoice.file_hash` only and every non-invoice re-upload reprocesses. A4/F5 says the
spec must widen the check or state the reprocess-in-v1 position explicitly; neither
happened, and silence is the one option A4/F5 names as unavailable.

Final status: **code complete, unverified, gap filed retroactively as BE Gap 381
(2026-09-02).** Items 11 and 12 are genuinely outstanding, as is the A4/F5 ruling.
