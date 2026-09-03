# Feature 6.1 — completion tasklist

Scoped by **architect**, 2026-09-03. Covers everything still open in the chat
retrieval hardening workstream: doc debt first (it is small and currently
misleading), then the remaining items in the founder's approved order.

Order is dependency-driven. Do not reorder without saying why.
Every task ends **uncommitted** — hard rule 6.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Track 0 — doc debt (blocking nothing, but wrong today)

Owner: **senior-dev** for 0.1–0.4, **functional-tester** for 0.5.
All docs-only. Ride these with the staged B1 commit rather than making a
separate change — the debt should not outlive the code it describes.

- [ ] **0.1 Gap 414 is `[ ]` in the tracker while C1 is live on master.**
  Flip to `[x]` and cite `ab4a986` + revision `--0000121` + the Gap 417 follow-up.
  A tracker that says "open" about shipped code is the one failure mode a tracker
  must not have. One line; do it first.
- [ ] **0.2 `feature_6.1_chat_retrieval_hardening_analysis.md` reuses a taken number.**
  `feature_6.1_vendor_flow_chat.md` is Direction-Aware Chat, built 2026-07-29.
  Rename to `feature_6.2_chat_retrieval_hardening.md`; update every reference
  (tracker Gaps 414–420, `run-status-2026-09-03.md`, the file's own headings).
  `git mv` so history follows. Collision-check `6.2` before writing, the same way
  gap numbers are checked.
- [ ] **0.3 `feature_26_chat_attached_documents.md` §E-4 — additive note.**
  Its Tier 3 vector branch (`search_attachment_chunks`, the `query_invoice_chunks`
  shape ~line 693) was reading an **empty** store on every dev revision until
  Gap 415. Record: what was true, which revisions, and what to re-verify after the
  next deploy. Additive only — hard rule 4.
- [ ] **0.4 `feature_6_rag.md` — additive note.**
  Owning spec for the SQL route and RAG; C1, B2 and B1 all changed its behaviour.
  Record the two-layer tenant guard, the Chroma retry contract, and the seven
  dependency spans. Additive only.
- [ ] **0.5 `test_coverage_map.md` — three suites missing.**
  `test_sql_tenant_guard_ast.py`, `test_chroma_fallback_retry.py`,
  `test_dependency_spans.py` all score **0** mentions. Add with their Postgres run
  dates and what each proves.

## Track 1 — close what is already built (needs one deploy)

Owner: **functional-tester**, with **infra-devops** for the deploy check.
One Azure check closes both. Do not start Track 2 before this: A1's whole claim
is measured with the instrument B1 adds, and an unverified instrument measures
nothing.

- [ ] **1.1 Deploy the B1 commit** (after the founder commits and pushes it).
- [ ] **1.2 B2 verification.** On the new revision: `RAG warm-up complete:
  chroma=ok` with **no** preceding `HttpClient failed` line, and
  `/health/readiness` returning `"chroma": "ok"`. If the fallback still fires,
  the 15 s warm-up budget is still too tight — record the measured connect time
  before changing the number.
- [ ] **1.3 B1 acceptance test.** One real chat turn shows a span per wrapped
  dependency, and the sum of spans plus LLM call durations is within **10%** of
  the turn's `latency_ms`. This is the test that finally explains — or fails to
  explain — the unaccounted ~5.5 s.
- [ ] **1.4 Record the ~5.5 s answer** in the analysis doc. The four ranked
  hypotheses are `_get_tenant_stats_summary` recompute (no Redis in dev),
  inline App Insights posts, `get_chat_history` + tiktoken, and
  `_full_record_block_for` reflection. B1 decides between them; do not guess.
- [ ] **1.5 Baseline the two token fields.** Record `cached_tokens` and
  `reasoning_tokens` per call across ≥10 turns — this is the **before** half of
  A1 and A4. Without it those two items can only be asserted.

## Track 2 — Block A, latency (founder's order)

Owner: **senior-dev**; **functional-tester** for every golden run.
Each item touches an LLM call, so each needs a golden-set before/after in
`docs/test_evidence/`. Hard rule 3 holds: none of these may move a figure.

- [ ] **2.1 A1 — `reasoning_effort="low"` + a completion cap** on SQL generation.
  Claim: 15.6 s → ~5.6 s. Proof: `reasoning_tokens` falls, generated SQL still
  correct on the golden set. **The risk is silent quality loss** — a cheaper
  reasoning budget that still returns *a* query. Golden set is the control.
- [ ] **2.2 A2-pre — gpt-4o capacity check.** Deployment cap is **10** today
  against `gpt-5-mini`'s 300. Classify plus summary on every turn will not fit.
  Decide: raise the cap, or drop A2. This is a blocking question, not a task.
- [ ] **2.3 A2 — classify / summary / RAG / narration onto the fast
  non-reasoning deployment.** Gated on 2.2.
- [ ] **2.4 A4 — reorder the prompt so the static prefix caches.**
  Azure needs a ≥1,024-token identical prefix in 128-token increments.
  Proof is `cached_tokens` rising — which is exactly why 1.5 must exist first.
- [ ] **2.5 A3 — stream the summary and the narration.** Value is bounded at
  ~2 s *perceived*; sequence it last in Block A on purpose.

## Track 3 — Block C, correctness

Owner: **senior-dev**; **functional-tester** for the runs.

- [ ] **3.1 C2 — answer-cache correctness.** `get_cached_answer` (~`4045`) runs
  before `classify_query` (~`4097`) and never consults `_is_narrowing_followup`,
  so a narrowing follow-up can be served another session's answer.
  **Must not change:** the F26 attachment gate at ~`4030–4035`, which returns
  before the cache read, and the `_invalidate_chat_answer_cache` prefix.
- [ ] **3.2 C3 — zero rows becomes a diagnosis.** Founder's rule: every recovery
  ends in a proposal the user confirms — *"I read X as Y — confirm?"*, one click,
  the same D4 gate Tier 3 uses. If SQL finds nothing, probe the vector store
  before answering. **Hard rule 3:** the vector probe answers text, it never
  supplies a figure SQL could not find. Scope `invoice_chunks_` only.
  2 d BE + 0.5 d FE.
- [ ] **3.3 C4 — rules → structure.** ~40% of rule text is deletable, not most.
  Includes ~1 d writing SQL for the 35 golden cases, which have none today.
  Largest item in the workstream; also the largest A4 win.
- [ ] **3.4 C5 — items 4, 3, 6.** Deferred by design. Gate: ≥100 Azure turns in
  telemetry **and** B2 verified. Do not start early.

## Track 4 — filed, out of scope, needs a decision

Not Feature 6.1 work. Listed so they are not lost.

- [ ] **4.1 Gap 416** — `invoice-be` has no `.dockerignore`; a local `docker build`
  would bake a developer's 17 MB `temp_chroma_db` into the image. CI builds from a
  clean checkout and is unaffected.
- [ ] **4.2 Gap 418** — four `test_rag.py` / one `test_chat_training.py` failures:
  three assert `200` from an endpoint returning `202` when the async queue is on;
  one fails either way on `post_chat_message() missing 'background_tasks'`.
- [ ] **4.3 Gap 421** — `test_each_band_is_still_the_live_panels_band` has raised
  `KeyError: 'tileSettings'` since the workbook table split, so Workbook alert
  bands have been unguarded. 8 cases.
- [ ] **4.4 Gap 420** — `test_a_queued_turn_that_raises…` takes
  `_turn_events(caplog)[0]` positionally and is order-dependent. Fix: select by
  `trace_id`, which it already sets.

---

## Sequencing, stated once

`0.1` → rest of Track 0 → **founder commits/pushes B1** → `1.1–1.5` →
`2.2` (blocking question) → `2.1` → `2.3` → `2.4` → `2.5` → `3.1` → `3.2` →
`3.3` → `3.4`. Track 4 whenever the founder schedules it.

Two hard dependencies worth repeating: **Track 2 cannot be evaluated before
Track 1** (no instrument, no before/after), and **A2 is blocked on a capacity
decision**, not on code.

## Standing constraints on every task above

- Nothing is committed by an agent. Every task ends in the Changes panel.
- Hard rule 2: "verified" cites a real Postgres run. Local compose is port **5433**.
- Hard rule 3: no model decides a figure.
- Tenant isolation only ever gets stronger.
- The F26 pre-route attachment gate is untouched.
- Every existing chat test keeps passing; the regression witness is derived by
  grepping the changed function names, not chosen by judgement (Gap 417).
- Every defect gets a tracker gap immediately, collision-checked repo-wide, in the
  same change as the code.

**Status: not started.** Created 2026-09-03 by architect at the founder's request.
