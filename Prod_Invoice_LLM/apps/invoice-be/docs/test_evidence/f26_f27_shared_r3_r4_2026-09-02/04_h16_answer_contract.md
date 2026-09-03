# H16 / V-27 — the answer contract now reaches the browser (BE Gap 386)

Date 2026-09-03. Persona: senior-dev (build), functional-tester (run).

## What was broken

`agents/query_agent.py` computed the whole P2.8 contract and every key was
discarded twice over:

  * `routers/chat.py::MessageResponse` declared none of them -> FastAPI stripped
    each one at serialisation.
  * `ChatMessage` had no column -> a session reload restored nothing.

So FE Gaps 376/380/383 built a confirmation card, a diff table, evidence blocks
and clarification buttons against a contract that could not physically arrive.
Every existing test asserted on the AGENT, so all of them were green throughout.

## What landed

  models.py                         ChatMessage.attachment_payload (JSON_VARIANT, nullable)
  alembic f5a6b7c8d9e0              add_chatmessage_attachment_payload, down_rev e4f5a6b7c8d9
  routers/chat.py                   ATTACHMENT_CONTRACT_KEYS (one tuple, both sides),
                                    extract_attachment_payload(), _with_attachment_payload(),
                                    9 optional fields on MessageResponse,
                                    persist in run_sync_chat_turn(),
                                    flatten on BOTH the POST return and the GET reload
  queue_worker/handlers.py          same attachment_payload= on the async write (H7-ready)

Applied to the dev Postgres: `alembic_version` = f5a6b7c8d9e0,
`chatmessage.attachment_payload` = **jsonb, nullable YES**.

## The bug inside the fix, found by the test and worth recording

The first implementation flattened the contract on the GET reload path only.
`post_chat_message()` ends `return MessageResponse.model_validate(assistant_msg)`,
which reads attributes off the ORM row -- and the contract lives inside that
row's `attachment_payload` dict, not as attributes. So the POST response carried
all nine keys as **null**: Gap 386 surviving its own fix, one layer down. Caught
because V-27 asserts on the HTTP response body rather than on the agent mock.
Both paths now go through `_with_attachment_payload()`.

## V-27 — 6 tests, all passing

  test_v27_a_confirmation_turn_reaches_the_client_and_survives_a_reload
  test_v27_a_comparison_turn_carries_its_diff_and_actions_both_ways
  test_v27_content_and_clarifying_turns_carry_their_own_keys
  test_v27_an_ordinary_chat_turn_is_byte_identical_to_before_h16
  test_v27_extractor_keeps_absent_keys_absent_rather_than_null
  test_v27_the_persist_side_and_the_wire_side_cannot_drift

Each contract test asserts twice: once on the POST body, once on the reloaded
session. A transient response field would satisfy the first and fail the second,
which is the distinction amendment B12 turns on.

Regression sweep: `test_h16_answer_contract.py` + `test_chat_attachments.py` +
`test_chat_doc_content_branch.py` + `test_chat_document_search.py` +
`test_chat_queue.py` + `test_chat_progress.py` + `test_documents_table.py`
-> **159 passed, 0 failed**.

## Evidence caveat

SQLite for the behaviour tests; the **migration** is Postgres-verified (applied,
column type and nullability read back from `information_schema`). The
`ENABLE_ASYNC_CHAT_QUEUE=False` pin in this file's autouse fixture is deliberate
and documented in the fixture -- see BE Gap 390 for why leaving it unpinned makes
a test depend on whether a container is running. V-16..V-18 (the async path) and
V-20/V-22 (Playwright against a real backend) remain open.
