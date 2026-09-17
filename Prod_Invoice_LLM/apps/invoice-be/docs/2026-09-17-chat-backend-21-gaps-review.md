# Closing review: `fix/chat-backend-21-gaps` — merged to `master`

**Merged:** 2026-09-17, fast-forward, `6a6ebc5..1fda8b7`
**Branch head at merge:** `1fda8b7` · **Base:** `6a6ebc5` — 0 behind, no merge commit needed
**Scope:** BE Gaps 570–611, the chat (no attachment) production-readiness audit of 2026-09-15 → 16
**Reviewed against:** real Postgres (`localhost:5433`), real Redis, a freshly created database per suite

> **Supersedes the round-1 version of this file**, which reviewed `de6ab56` and sent the branch back
> over four items. Commit `1104e6d` fixed all four; this file records the finished state.

---

## Outcome

Merged. 42 gap entries: **6 `[x]`**, **35 `[~]`** code-complete/unverified, **1 withdrawn** (BE Gap 575).
Two developers split the work — Krushna Sonalkar took 573–575, 578, 581–586, 593–594, 596, 598–599, 601,
604, 606, 609–611; devashish-patel-18 took the rest — and `fbed1bc` reconciled the two halves across
19 files.

## What the branch delivers

Tenant-user chat isolation, `readonly` API-key refusal, per-session locking with an immediate 409,
one-runner-per-turn de-duplication, a self-healing concurrency lease with a scheduled reaper, answer-cache
scoping and O(1) invalidation, output DLP, an answer contract gate covering figures *and* dates, prompt
delimiter escaping, chat-read audit rows, and per-turn forensic metadata. Roughly 5,300 lines across
50 files.

## Review rounds

**Round 1** (against `de6ab56`) found four `[x]` claims whose cited evidence did not reproduce on
Postgres. Fixed in `1104e6d`: claim release, self-healing 409, the reaper scheduled in Bicep, and two
holes in the BE Gap 601 ceiling.

**Round 2** (against `1104e6d`) audited the branch against `/gap-work` and `/done` rather than re-testing
it. The code held up; the closure discipline did not. Fixed in `1fda8b7`:

| # | Finding | Resolution |
|---|---|---|
| 1 | **BE Gap 603 closed only the SSE door.** The polling fallback ran `statusData.status === "failed" \|\| attempts >= maxAttempts` as one branch, so a 120s poll timeout — the FE giving up, not the job failing — set `status: "failed"`, which `MessageBubble` renders as a red **"Query Failed"** card. Users re-ask; the uncancellable job runs twice. The duplicate the gap exists to prevent, relocated rather than removed | Condition split; a timeout now mirrors the `still_running` branch |
| 2 | **The branch did not compile.** `tsc --noEmit` returned `TS2367` and `TS2339` in BE Gap 603's own SSE half — `still_running` is absent from `ChatJobStatus`, `message` absent from `ChatStreamEvent`. `master` typechecks the file clean, so both were branch-introduced, and two review rounds missed them because nobody ran `tsc` | `ChatStreamEvent` widened; `ChatJobStatus` deliberately left alone, as it is also `ChatMessage.status` |
| 3 | **BE Gap 601 was `[x]` while its own entry ended "Founder call, open."** The two developers fixed it differently and the merge kept one shape without settling the question | Founder ruled 2026-09-17: **degrade, do not refuse**. Recorded in the entry and in the `ChatQueueUnavailableError` docstring, which had described the two halves of this branch as if they were separate branches |
| 4 | **79 bare `Gap NNN` cites** in the 570–611 range across 25 files, against `/gap-open` §3 — BE Gap 378 and FE Gap 378 collided once already, and this branch edits FE files | All prefixed `BE Gap` |
| 5 | **`feature_6_rag.md` changed by zero lines** while 42 gaps rewrote the code it describes. Nine new behaviours and two new service modules undocumented; the "as built" section dated 2026-09-04 | Rewritten, 2,120 → 310 lines; history split to `feature_6_rag_history.md` |
| 6 | **No entry stated what its fix does *not* handle** (`/done` #11), and only 2 of 42 gave call sites found vs fixed (#10) | Backfilled on the six `[x]` entries; the 35 `[~]` get theirs at closure |
| 7 | **Evidence cited as counts** — `(8 passed)` — not the verbatim output line `/gap-work` §4 requires | Real result lines pasted into the six `[x]` entries |

## Evidence

Real Postgres, fresh database per suite, `-p no:randomly`:

```
test_gap572_user_chat_isolation             8 passed in 21.72s
test_gap587_session_lock_contention         8 passed in 21.12s
test_gap600_chat_queue_dedup                5 passed in 17.07s
test_gap605_concurrency_lease_and_reaper    6 passed in 14.63s
test_gap576_577_cache_scope_invalidation   39 passed in 10.75s
test_c2_cache_correctness                  18 passed in 10.19s
test_chat_queue                            21 passed in 41.62s
test_chat_progress                         13 passed in 47.12s
test_chat_training                         29 passed in 52.19s
test_chat_attachments                      49 passed in 73.90s
test_chat_doc_content_branch               70 passed in 44.76s
test_chat_memory_multidoc                  23 passed in 73.06s
test_widget_token                          50 passed in 76.15s
test_chat_sql_table_allowlist              53 passed in 14.09s
test_entity_resolver                       17 passed in 12.57s
test_full_records                          14 passed in 11.72s
test_no_hardcoding                          4 passed in  8.05s

alembic upgrade head -> e6f7a8b9c0d1, clean on a virgin database
tsc --noEmit -> zero errors in useChatSession.ts and types/chat.ts
```

**Not a regression:** `test_audit.py` fails 3 tests (`audit_logs_actor_user_id_fkey`) on Postgres. The
same 3 fail identically on `6a6ebc5`; the SQLite runs never enforced the FK.

**Accepted carve-out:** `test_chat_sql_quality.py` returns `4 failed, 149 passed in 107.43s` on Postgres.
Four tests assert the SQLite dialect by design. Founder ruling 2026-09-17 — with `TEST_DATABASE_URL`
unset the suite falls back to SQLite and is green, so no CI or day-to-day run is affected. See BE Gap 570.

## Carried forward — not fixed by this merge

1. **No FE build or typecheck runs anywhere in this repo's verification path.** That is why a
   non-compiling branch reached review twice. The most valuable item on this list; worth a gap.
2. **The BE Gap 605 reaper is declared in Bicep, not deployed.** No Azure apply has run. Until then
   `CHAT_INFLIGHT_LEASE_TTL_SECONDS` (300s) is the only self-healing mechanism.
3. **35 entries are `[~]`.** Each control is tested in isolation; no adversarial pass has been run
   against the assembled §§9–10 surface.
4. **The ported chat fixtures need a virgin database.** Run against a schema already at head they
   produce `61 failed, 559 passed, 308 errors`. Consequence: the three new migrations are exercised by
   `alembic upgrade head`, never by the suite.
5. **`ChatSession` isolation is enforced in the router, not the database.** No RLS policy sits behind
   the seven call sites, so a future query path that bypasses them is unguarded.
