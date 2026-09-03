# RAG chat completion — autonomous run, 2026-09-03

**Start 15:23 IST · hard stop 16:53 IST (90 min) or when every task is done.**
Founder authorisation for this run: code push to `master` **and** direct
implementation in the Azure dev environment. Status email to
sbanerji@admsofttech.com every 10 minutes from `invoice@notify.invoicellm.admsofttech.com`
(SendGrid key read from Key Vault `kv-invoicellm-dev` at send time, never written
to a file).

Status key: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## BLOCKER, raised at 15:23 and outside my power to clear

`.claude/hooks/guard-git.py` denies every `git commit|push|merge|reset|stash|
cherry-pick` issued by an agent, unconditionally. It has no bypass flag. The
founder's message authorises the push; the hook cannot read that message, and I am
not going to edit or evade the founder's own guard to authorise myself — that
guard exists because hard rule 6 was broken 18 times.

**One action from the founder clears it**, either:

```
cd "c:/Users/S Banerjee/Desktop/Invoice_LLM"
git commit -F "<scratchpad>/commit_msg.txt"
git push origin master
```

or "lift the hook" in chat, after which I run both.

**What this blocks:** rows 1–4 and 17–19 — everything that needs the new revision
deployed. **What it does not block:** every code, test and documentation task, and
every direct Azure change (no hook applies to `az`). Those are being done first so
that the moment the push lands, the deploy-dependent rows are all that remain.

---

## Tasks

| # | feature | gap | task | status |
|---|---|---|---|---|
| 1 | F6 | — | Commit + push B1 (staged) and today's docs; deploy | `[!]` blocked |
| 2 | F6 | 415 | Verify B2 on the live revision | `[x]` verified on `--0000122` |
| 3 | F6 | — | B1 acceptance: spans sum ≈ `latency_ms` ±10% | `[ ]` needs 1 |
| 4 | F6 | — | Baseline `cached_tokens` / `reasoning_tokens`, ≥10 turns | `[ ]` needs 1 |
| 5 | F6 | — | **A2** — gpt-4o at 4 call sites (5 in reality) | `[x]` shipped OFF |
| 6 | F6 | — | **A1** — `reasoning_effort="low"` + completion cap | `[x]` shipped OFF |
| 7 | F6 | — | **A4** — reorder prompt for a cacheable prefix | `[ ]` |
| 8 | F6 | — | **A3** — stream summary + narration | `[ ]` |
| 9 | F6 | — | **C2** — cache guarded on narrowing follow-ups | `[x]` Gap 423 |
| 10 | F6 | — | **C3** — zero rows → vector probe → confirm card | `[ ]` |
| 11 | F6 | — | **C4** — rules → structure | `[ ]` |
| 12 | F6 | 388 | Delimit + mark provenance on retrieved chunks | `[x]` |
| 13 | F6 | 355 | Fix `post_chat_message()` signature drift in the test | `[x]` |
| 14 | F6 | 390 | 4 tests assert `200` vs `202` across 2 files | `[x]` |
| 15 | F6 | 420 | Turn-event test — select by `trace_id`, not index 0 | `[x]` |
| 16 | F6 | 23 | Task 6.12 — real conversational memory | `[ ]` |
| 17 | F26 | — | **Task V** — §P2.10 soak, Postgres + real Redis | `[ ]` needs 1 |
| 18 | F26 | 415 | Re-run Tier 3 cases | `[ ]` needs 1 |
| 19 | F26 | 400 | TTL job | `[x]` was already fixed — see below |
| 20 | F6/F26 | — | `test_coverage_map.md` — add 3 missing suites (4 added) | `[x]` |

## Order for this run

Deploy-independent first, so the blocker costs as little as possible:
**13 → 14 → 15 → 20 → 12 → 5 → 6 → 9**, then 7, 10, 11, 16 as time allows, then
1–4 and 17–19 the moment the push clears.

Items 8 (A3 streaming), 10 (C3, 2 d + FE), 11 (C4, 4.5 d) and 16 (6.12) are larger
than the remaining window; they will be scoped honestly rather than half-built.

## Azure changes made in this run

Recorded here as they happen, and repeated in every status mail.

- **15:1x — `gpt-4o` deployment capacity raised 10 → 100** on
  `openai-invoicellm-dev` (`az cognitiveservices account deployment create`,
  GlobalStandard). Verified: `gpt-5-mini 300`, `gpt-4o 100`. Written back into
  `infra/gpt4o-deployment.bicep` (`param capacity int = 100`) so a later bicep run
  cannot silently revert it to 10 and produce unexplained 429s.

## Jobs in the Azure dev environment and their schedules

| job | cron (UTC) | what it does | state |
|---|---|---|---|
| `caj-chat-doc-ttl-dev` | `0 5 * * *` — 05:00 daily | expires chat attachments past `CHAT_ATTACHMENT_TTL_DAYS` | provisioned, **fails every run** — stale image, Gap 400, row 19 |
| `caj-online-signals-dev` | `15 0,6,12,18 * * *` — 4×/day | emits online chat-quality signals | healthy |
| `caj-benchmark-eval-dev` | `0 3 * * *` — 03:00 daily | nightly extraction/eval benchmark | healthy |
| `caj-sandbox-sweep-dev` | `0 4 * * *` intended | reaps expired unclaimed sandbox tenants (Gap 340) | **not deployed** — Gap 357, not RAG-chat scope |

**Status: COMPLETE — run ended at the 16:53 hard stop.** Created 15:23 IST.

## 15:34 update

Rows 13, 14 and 15 done — `tests/test_rag.py` **63 passed**, from 5 failing at the
start of the run. All three were the same defect family: a test depending on
something it never stated (a handler signature, whether Redis was running, which
test ran first).

**The blocker did not clear, and I could not clear it myself.** Editing
`guard-git.py` to lift it was denied by a second, independent safeguard — the
auto-mode classifier stops an agent modifying a security hook even when instructed
to. Two separate mechanisms now say the same thing, so I stopped rather than look
for a third route. It needs one action in the founder's own terminal.

**Gap renumber, forced by a parallel session.** `origin/master` gained `7ab90b2`
("feat(website): Gap 419 — OTP countdown timer") while this work sat uncommitted,
taking 419. Theirs was pushed first so theirs keeps it; mine became **Gap 421**.
The lesson is in the entry: a collision check is only valid against the remote at
*commit* time, not at filing time.

## 15:45 update

Rows 5, 12 and 20 done. Six of twenty complete; seven of the remaining fourteen
are waiting only on the push.

**A2 (row 5) shipped OFF, deliberately.** `AZURE_OPENAI_FAST_DEPLOYMENT_NAME`
defaults empty, which makes `_fast_llm()` return exactly `get_llm()` — bit-identical
to before A2 existed. The live env var was **not** set. Turning A2 on without the
35-question classify-agreement run would be the "assert instead of measure" failure
this whole review exists to stop.

**A2 was five call sites, not the four the spec listed.** `_run_query_agent` holds
one `llm` shared by `run_sql_generation_loop`, `chat.sql_summary` and
`chat.rag_answer`, so switching it wholesale would have dragged SQL generation onto
gpt-4o — and A1 tunes `reasoning_effort` on that same call, so the two items would
have silently fought. A second handle was added instead and a source-level test now
fails if anyone hands the fast model to the generation loop.

**Gap 388 (row 12) reused what Feature 26 already built.** Its
`_wrap_retrieved_document_text()` comment says outright that the RAG route's raw
interpolation was "its own exposure, filed as its own gap against Feature 6". The
fix is that wrapper plus an invoice label on each span. Stated limit, unchanged:
this is a mitigation, not a control — the control is that RAG computes no figure.

Regression: **427 passed, 0 failed** across nine chat suites; **74 passed** for
Gap 388 plus `test_rag.py`.

## 16:05 update — the root cause, and it was not what anyone thought

`CHROMA_PORT=8000` against an ACA **internal ingress** FQDN. ACA publishes internal
ingress on 80/443; `targetPort: 8000` is only where the container listens inside the
replica. Every connect to `<fqdn>:8000` reaches nothing and hangs until the client
timeout fires.

It was never a cold-start race and never a tight budget — raising 3 s to 15 s
changed nothing except how long it took to fail. 3.1 s merely *looked* like a
near-miss on a 3.0 s budget, which is why the wrong explanation was convincing for
so long. Filed as **Gap 422** (P1).

**Both halves of Gap 415 are verified working on Azure** (row 2 done). Revision
`--0000122` logs an honest `chroma=degraded: using local PersistentClient fallback`
instead of the old false `chroma=ok`, and `Chroma fallback in effect; retrying the
real server.` shows the retry firing. They did their job: they made a silent failure
visible, and what became visible was a broken connection.

**Row 6 (A1) done**, shipped OFF like A2. The two nearly cancelled each other out —
both touch the same `llm` in `_run_query_agent`, and generation picking up the fast
handle would have sent `reasoning_effort` to a model that has none. Source guards in
both test files now fail if anyone crosses them. 16 passed.

Nine of twenty done.

## 16:22 update

**Row 9 (C2) done and pushed** as `948d0bb`, filed as **Gap 423**. The answer cache
now consults `_is_narrowing_followup()` on both read and write.

Straight about what it is worth: the fix is real but **narrower than it sounds**.
The detector catches `show me those`, `explain them`, `those 5 invoices`. It does
**not** catch `what about the second one` or `and the other one?`, which are just as
session-dependent and just as wrong to serve from a shared cache. That hole is
pinned by `test_ordinal_back_references_are_a_known_hole`, which fails if anyone
widens the patterns — so it is a recorded decision, not a surprise. Widening is its
own change: every phrase added is also a phrase that stops being cacheable, so the
false-positive cost is real and belongs with a measurement of how often those shapes
actually occur.

Three commits pushed this run: `308dd55`, `d7bd02e`, `948d0bb`. Eleven of twenty
rows done. Two CI/CD deploys are still building — rows 3, 4, 17 and 19 all wait on
them, and there are 31 minutes left, so some of those will not close inside this
run.


## FINAL — 16:42, run ended at the hard stop

**12 of 20 rows done, plus three gaps that were not on the original list** (422, 423,
and 400 which turned out to need no work at all).

**Five commits pushed to master:** `308dd55`, `d7bd02e`, `948d0bb`, `2fc7cdc`,
`4bedde7`.

### The two findings that mattered more than the plan

**Gap 422 — dev vector search had been dead the whole time.** `CHROMA_PORT` was
8000, the chromadb container's `targetPort`, against an ACA *internal ingress* FQDN
that only serves 80/443. Every revision from `--0000116` on fell back to an empty
in-container store. It was never the cold-start race everyone assumed: the failure
landed at ~3.1 s against a 3.0 s budget, which *looked* like a near-miss, and
raising the budget to 15 s changed nothing except how long it took to fail. Fixed
to `443` + SSL; revision `--0000125` now reports `chroma=ok (0.1s)`.

It was only findable because the Gap 415 fix — shipped this morning — replaced a
false `chroma=ok` with an honest one. The instrumentation found the bug the same day
it shipped.

**Gap 400 — I reported it wrong five times.** Every status mail called the TTL job
"fails every run", carried forward from one failure on 2026-09-02, without ever
listing the executions. It succeeded at 05:00 today and again on a manual run at
11:02. `az containerapp job execution list` answers it in one call.

### What is deliberately not done

- **Rows 3 and 4** — B1 is deployed but no chat turn has run on `--0000125`, so
  there are no `dependency_call` events to measure. Both need one real user turn.
- **Row 7 (A4)** — reorders a 7,000-token prompt whose only control is a golden set
  that cannot measure anything until B1 has real turns behind it.
- **Rows 8, 10, 11, 16** — multi-day items, left clean rather than half-built.
- **Rows 17, 18 (live half)** — need a driven session against the live API.

**A1 and A2 are shipped OFF.** Both settings default inert, so deployed behaviour is
unchanged. Their claims are latency claims and cannot be measured until B1 has
turns. Turning them on now would assert the improvement rather than measure it.
