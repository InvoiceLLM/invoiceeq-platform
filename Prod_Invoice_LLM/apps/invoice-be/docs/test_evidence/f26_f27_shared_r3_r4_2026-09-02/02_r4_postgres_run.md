# R4 — the F26/F27 suites against real Postgres + Redis + Chroma

Date 2026-09-02. Persona: functional-tester. Hard rule 2 evidence.

    uv run pytest tests/test_documents_table.py tests/test_chat_attachments.py \
      tests/test_chat_doc_content_branch.py tests/test_chat_document_search.py \
      tests/test_chat_queue.py tests/test_chat_progress.py tests/test_rag.py \
      -q -p no:cacheprovider --no-header -rfsE

    5 failed, 211 passed in 52.48s

Stack: `invoice-postgres-local` (healthy, :5433), `invoice-redis-local` (healthy,
:6379), `invoice-chromadb-local` (:8001), `invoice-azurite-local` (:10000-1) — all
four brought up for this run. Raw log: `03_r4_raw_pytest.log`.

## The headline is the skip count: ZERO

`tests/test_documents_table.py::pg_engine_or_skip()` skips unless it reaches a real
`postgresql://` server. It did not skip. **T-E10-1 through T-E10-5 executed against
real Postgres and passed**, which every prior record in both specs listed as
"built, never run":

  R-27-20  non-INVOICE ingestion leaves zero `invoice` rows, one `documents` row,
           placeholder deleted in one transaction        -> PASS (Postgres)
  R-27-21  /dashboard/insights byte-identical before/after -> PASS (Postgres)
  R-27-22  billing dedup union, second tenant still charged -> PASS (Postgres)
  R-27-23  docs_{tenant} cosine + unreachable from query_invoice_chunks -> PASS
  R-27-24  cross-tenant GET /documents/{id} -> 404, list scoped, soft-delete hidden -> PASS

Feature 26 side, all green with real infra rather than SQLite: 33 + 39 + 11 across
`test_chat_attachments.py`, `test_chat_doc_content_branch.py`,
`test_chat_document_search.py`, plus `test_chat_queue.py` and
`test_chat_progress.py`. **V-19's regression bar is met.**

## The 5 failures — none is a Feature 26 or 27 defect

1. `test_documents_table.py::test_the_lifecycle_functions_never_open_a_collection_without_the_metadata`
   — **BE Gap 389, fixed in this same pass.** The test asserted
   `"get_or_create_collection(" not in inspect.getsource(fn)`; that source includes
   the docstring, and `delete_document_chunks`'s docstring names the function while
   explaining why it does not call it. Re-asserted over the parsed `ast` call graph,
   with a negative control. **The prior reading of this as a real G10 lifecycle
   defect is withdrawn** — those functions exist and are correct
   (`chroma_client.py:639/676/704/723`).
2-4. `test_rag.py::test_agent_internal_rollback_does_not_drop_the_user_message`,
   `::test_agent_failure_still_pairs_a_fallback_reply_with_the_user_turn`,
   `::test_rag_citations_drop_ids_with_no_matching_invoice_row` — **BE Gap 390.**
   All three `assert res.status_code == 200`; with `.env`'s
   `ENABLE_ASYNC_CHAT_QUEUE=true` and Redis now reachable the endpoint correctly
   returns `202 Accepted` with a `job_id`. They passed historically only because
   Redis was down. Not touched by either feature.
5. `test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message` —
   the long-recorded pre-existing `TypeError: post_chat_message() missing 1
   required positional argument: 'background_tasks'`, named in Gaps 370/373/374.

## What R4 does NOT cover, stated so it is not over-claimed

V-24's warm-cache assertion (needs Redis primed directly), V-25's live injection
probe (never attempted), V-16..V-18 (async attachment turns; H7 unbuilt), V-20/V-22
(Playwright against a real backend; blocked on H16), and T-OFF-1 / T-R-6 (need a
committed golden). Those remain open.
