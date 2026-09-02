# Phase 3 functional-test pass -- Gaps 364/365/366 (RE-RUN, Docker engine confirmed healthy)

Scope: `.claude/tasklists/architect-phase2-sage-feature-build.md` Phase 3, 30-minute
hard-stop box, 2026-09-01. This supersedes the earlier same-day attempt (first
`README.md` version in this directory) which was genuinely blocked by Docker
Desktop's engine being down. That blocker is now resolved: `docker compose ps`
confirmed `invoice-postgres-local` (healthy, `0.0.0.0:5433`) and
`invoice-redis-local` (healthy, `0.0.0.0:6379`) up before this pass started;
`alembic upgrade head` was run against the real Postgres instance first (it had
never been migrated -- `alembic current` returned nothing) and reached
`c2d3e4f5a6b7` (head, includes the Gap 366 `chat_attachments` migration).

## How this was run

One consolidated script, `02_real_postgres_redis_verify_script.py` (copied here
verbatim, ~550 lines), executed with `.venv/Scripts/python.exe` against real
Postgres (`postgresql://postgres:localpassword123@localhost:5433/invoice_db`)
and real Redis (`redis://localhost:6379/0`) -- no dependency override on
`get_db_session` or `get_redis_client()` anywhere, so every DB write and every
Redis op in the sections below hit the real services. Full raw output:
`02_real_postgres_redis_run.log`.

LLM calls are mocked (`agents.query_agent.get_llm`/`classify_query`/
`execute_generated_sql` patched with scripted responses) for the sections that
exercise a chat turn. This matches this repo's own established narrow-test
convention (`tests/test_chat_progress.py`, `tests/test_chat_attachments.py`
both do the same) -- hard rule 2 is about DB/Redis being real, not the model
call, and a live Azure OpenAI round-trip per turn would not fit the 30-minute
box. Everything else in those turns (Postgres writes, Redis pub/sub, the real
`chat_session_lock`, the real `/chat/jobs/{id}/stream` endpoint) is real.

Multi-tenant HTTP calls use `app.dependency_overrides` on
`get_tenant_context`/`get_tenant_or_api_key_context`, not the `test_<uuid>`
mock-auth Bearer token. The first attempt used the token vocabulary the rest
of this repo's test suite uses (`Authorization: Bearer test_<uuid>`) and hit a
real, repo-relevant finding: against a persistent real Postgres, the
`ALLOW_MOCK_AUTH` provisioning path keys off a fixed `MOCK_USER_ID`/email, so
the second mock-auth call in the same process reused the `User` row (and its
tenant) provisioned by the first call, silently ignoring the UUID embedded in
the second token. Every existing test in this repo that uses `test_<uuid>`
tokens runs on a fresh empty SQLite database per test, so this never surfaces
there. Confirmed directly with two throwaway repro scripts (not committed):
`get_tenant_or_api_key_context()` returned the first mock tenant regardless of
the UUID in a second call's token, in the same process, against real Postgres.
Switched to `app.dependency_overrides` (the same mechanism
`test_job_isolation_on_postgres` already uses in `tests/test_chat_queue.py`) to
pin tenant identity deterministically; the DB/Redis effects verified are
unaffected by this -- only the auth resolution path differs from a live
Clerk/mock-token request. Flagging this back rather than fixing it, per this
pass's own scope boundary ("fixing anything found -- file it back, do not
patch it"): it is a test-harness footgun specific to reusing `ALLOW_MOCK_AUTH`
tokens against a persistent database, not a defect in Gaps 364/365/366.

## T1 (Gap 364) -- VERIFIED, real Postgres + real Redis

1. 4th concurrent job rejected, 3 in flight complete, counter returns to 0 on
   both completion paths. Real Redis (`chat_inflight:{tenant}` INCR/DECR): 3
   real `enqueue_chat_job()` calls accepted, counter reads `3`; 4th raises
   `ChatQueueCapacityError(active=4, limit=3, retry_after_seconds=5)`, counter
   still `3` (slot handed back). `complete_job()` -> `2`, `fail_job()` -> `1`,
   `release_tenant_slot()` -> `0`. PASS.
2. Slot-leak fix, real Redis counters, simulated `lpush` failure. A wrapper
   delegates INCR/DECR/GET/SET to the real Redis client and only fakes `lpush`
   raising once. `enqueue_chat_job()` still returns a queued status (the
   swallow is deliberate, non-500) but the real Redis counter reads back `0`
   -- the reservation was rolled back for real, not against a mock. PASS.
3. Real HTTP 429 + `Retry-After: 5`, zero orphan `ChatMessage` row on real
   Postgres. A real `Tenant` + `ChatSession` row written to Postgres; the real
   Redis counter for that tenant primed to `3` (simulating 3 genuinely
   in-flight jobs); `POST /chat/sessions/{id}/message` (async queue path
   enabled) -> 429, `Retry-After: "5"`, body about 3 chat turns already
   running. Queried real Postgres immediately after: 0 `ChatMessage` rows for
   that session, session title unchanged -- confirms the router does not
   write the user row before `enqueue_chat_job()` succeeds. Released the
   counter back to 0 and reposted -> real 202, real `enqueue_chat_job` log
   line, 1 row queued. PASS. `be_features_tracker.md` L897's corrected claim
   (Gap 364's own text) is consistent with this real-infra behaviour.

## T2 (Gap 365) -- PARTIALLY VERIFIED; 2 of 3 checks did not reproduce on real infra

1. Per-session lock -- VERIFIED, real Redis. Two threads racing
   `chat_session_lock()` against the real Redis client: same `session_id` ->
   both acquire the lock (True, True) but never overlap (overlapped=False);
   two different `session_id`s -> both acquire and DO overlap
   (overlapped=True, i.e. genuinely parallel). PASS, real `SET NX`/`GET`/`DEL`
   against `localhost:6379`.
2. Live-progress SSE transcript (flip criterion 1) -- real infra exercised,
   criterion NOT MET on this run. A real `ChatSession`/`ChatMessage` row
   written to Postgres; a background thread opened a real streaming HTTP
   connection to `GET /chat/jobs/{id}/stream` (the actual FastAPI route,
   including its real Redis pub/sub `pubsub.subscribe()`/`get_message()` loop
   -- not a mock of the endpoint); the job ran for real via
   `handle_process_chat_job()` with a scripted SQL-repair (attempt 1 fails,
   attempt 2 succeeds) so the "each repair attempt shown separately" half of
   the bar is testable. Captured transcript: queued, received,
   understanding_question, route_selected, completed -- 5 distinct steps,
   missing building_query/generating_sql/running_query/summarizing_results/
   answer_ready entirely, and zero generating_sql events (so the
   per-attempt-visibility half is also unmet). This does not mean the seams
   are not being published -- the worker log in
   `02_real_postgres_redis_run.log` shows the turn really did run 2 SQL
   attempts, get a route, and complete, all inside roughly 400ms. The likely
   mechanism (not chased further -- in scope for a report-back, not a fix):
   `routers/chat.py::stream_chat_job()`'s `event_generator()` polls
   `ChatQueueService.get_job_status()` on every loop iteration (around
   `chat.py` L792-796) as a fallback alongside the pub/sub read, and once
   `complete_job()` writes the cached status to "completed" that periodic
   check can win the race and break the stream before every earlier pub/sub
   message has been drained -- on a turn fast enough (mocked LLM, no network
   latency), that race is easy to lose. This is a genuine real-timing finding
   distinct from the repo's own SQLite narrow test
   (`test_chat_progress.py::test_a_sql_turn_publishes_at_every_real_seam`,
   which reads `on_progress` directly with no HTTP/pub-sub layer in between
   and correctly shows 7 steps) -- flagging back, not fixing: the underlying
   seam instrumentation in `agents/query_agent.py` is not what failed here,
   the `/stream` endpoint's own polling-vs-pubsub race is the suspect. Flip
   criterion 1: FAIL on this real run (5 distinct steps captured over HTTP, 0
   repair attempts individually visible).
3. Gap 237 route-override visibility under real infra -- NOT REPRODUCED,
   likely a test-input mistake, not re-run due to the time box. A second real
   turn (`classify_query` -> "RAG", `get_prior_turn_sql` patched) was run to
   check the `route_override` event appears on the real Redis channel. It did
   not fire (route_override events published: none, route stayed RAG).
   Comparing against the passing SQLite test
   (`test_chat_progress.py::test_the_gap_237_route_override_is_visible_on_the_channel`),
   that test's exact phrasing is "can you explain the 3 USD ones in detail?"
   -- this run used "can you explain the USD ones in detail?" (missing the
   number), which is very likely why `_is_narrowing_followup()` did not
   classify it as a narrowing follow-up. Not re-run given the time box; noted
   as an inconclusive test-input issue, not a code finding, and left as NOT
   VERIFIED on real infra rather than claimed passing.

## T3 (Gap 366) -- VERIFIED, real Postgres + real Azurite blob storage

Full flow driven through the real HTTP endpoints in `routers/chat_attachments.py`
against real Postgres, with real Azurite blob storage (confirmed via the real
Azure Blob SDK PUT/GET calls in the log) and the deep OCR/extraction call
mocked (`queue_worker.handlers._run_ocr`, `agents.extraction_agent.run_extraction_agent`)
-- the same convention as elsewhere in this pass, kept inside the time box.

- Upload: `POST /chat/sessions/{id}/attachments` with a real PDF-content-type
  file -> 200, real `ChatAttachment` row confirmed via a direct Postgres read,
  real `blob_path` under `azure://invoices/tenants/.../chat-attachments/`.
- D2 (no `Invoice` row): queried real Postgres for `Invoice` rows under the
  test tenant post-upload -- still exactly the 1 pre-seeded invoice, 0 created
  by the attachment. PASS.
- D3 (no billing/ingestion quota moved): real `Tenant` row's quota-shaped
  fields unchanged by the upload. PASS.
- Tier 1 exact PO match: `find_candidate_invoices()` against real Postgres
  rows -> tier=1, returns exactly the invoice sharing the normalised PO
  number. PASS.
- Tier 2 fallback: a second real invoice with no PO number, same vendor,
  in-window date -> tier=2, found via vendor+date fallback only when Tier 1 is
  empty. PASS.
- Zero-match path: unmatched PO + vendor -> tier=0, empty list, not widened.
  PASS.
- Confirmation gate: an answer-turn issued (`qa._run_query_agent(...,
  attachment_id=...)`) BEFORE `confirm-matches` -> `classify_query` and
  `get_llm` both never called, response carries an
  attachment_match_confirmation payload, no attachment_comparison key at all.
  PASS -- never a silent guess.
- Confirm-matches: real `POST /chat/attachments/{id}/confirm-matches` -> 200,
  real Postgres row's `confirmed_invoice_ids` updated.
- Post-confirmation answer turn: deterministic diff computed against the real
  Postgres invoice row and the real attachment row -- grand_total delta 0.0,
  status match (an exact match by construction of the test data). PASS.
- Currency-mismatch hard stop: a real EUR invoice vs. the INR reference ->
  outcome currency_mismatch, fields empty (nothing compared), reason string
  names both currencies. PASS.
- Tenant isolation, all 3 `chat_attachments.py` endpoints, real Postgres, 2
  real tenants: tenant B's GET on tenant A's attachment -> 404; tenant B's
  confirm-matches on tenant A's attachment -> 404; tenant B's upload into
  tenant A's session -> 404; tenant A (owner) still reads its own attachment
  -> 200. PASS.

## T4 -- flip-criteria evaluation, real evidence, decision: flag stays False

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | 6+ distinct SSE steps + per-attempt repair visibility | FAIL | T2 item 2: 5 distinct steps captured over the real `/stream` endpoint, 0 repair-attempt events. Likely a polling/pub-sub race in `stream_chat_job()`, not a seam-instrumentation gap -- the criterion is about the SSE transcript as delivered, which is what failed. |
| 2 | 4th job real-429 while 3 in flight complete | PASS | T1 items 1 and 3 |
| 3 | Narrowing follow-up still routes to SQL under load | FAIL (inconclusive) | Lock mechanism itself independently verified real (T2 item 1, PASS); the override-visibility half did not reproduce this run, plausibly a test-input mistake (missing digit in the probe question) -- not re-run inside the time box, scored FAIL rather than assumed PASS |
| 4 | Failed job returns `chat_inflight:{tenant}` to 0 | PASS | T1 item 1 |
| 5 | Redis unreachable still answers via sync path, no 500 | NOT EXERCISED | Out of the 30-minute box this run |

Decision: `ENABLE_ASYNC_CHAT_QUEUE` stays False. 2 of 5 criteria pass outright
(2, 4), 1 is a real mechanism pass with an inconclusive companion check (3), 1
fails on real-timing evidence (1), and 1 was not attempted (5). D7 requires
all five, on one run, before a dev-only flip -- this run does not clear that
bar. No `config.py` change made.

## T5 -- narrow regression suite, real Postgres + real Redis up

`tests/test_chat_queue.py tests/test_chat_progress.py tests/test_chat_attachments.py`
-> 56 passed (`03_t5_narrow_suite_real_infra_up.log`), run with the real
Postgres/Redis containers up. No `--postgres` flag or special invocation
exists or is needed -- read the fixtures directly: all three files hardcode
`sqlite:///:memory:` engines and override `get_db_session`, except
`test_chat_queue.py::test_job_isolation_on_postgres`, which explicitly checks
`DATABASE_URL` is `postgresql://` and skips itself otherwise. With real
Postgres reachable this run, that one test executed for real -- previously
skipped every time no local Postgres existed -- and is included in the 56.
The other 55 are still SQLite/mocked-Redis by construction of their own
fixtures -- having the containers running does not change what they connect
to. This is why T1/T2/T3 above were driven by a separate real-infra script
rather than by asking these files to point at Postgres: they cannot, without
editing their fixtures, which is out of this pass's scope.

## Summary

| Item | Status |
|---|---|
| T1 -- Gap 364 | VERIFIED, real Postgres + real Redis |
| T2 -- Gap 365 | PARTIAL -- per-session lock VERIFIED real; SSE transcript flip-criterion FAILED real; route-override check inconclusive |
| T3 -- Gap 366 | VERIFIED, real Postgres + real Azurite, all sub-checks including tenant isolation |
| T4 -- flip decision | False, unchanged -- 2/5 criteria pass, 1 fails, 1 inconclusive, 1 not attempted |
| T5 -- narrow regression | 56/56 passed with real infra up; only 1 of the 56 actually executes against Postgres by its own design |

Raw evidence: `02_real_postgres_redis_run.log`, `02_real_postgres_redis_verify_script.py`, `03_t5_narrow_suite_real_infra_up.log`.
