# architect → senior-dev → functional-tester — Phase 2 SAGE/Chat feature build

Founder-approved scope, 2026-09-01. Builds on the completed analysis at
`architect-phase2-sage-chat-analysis.md`. Three time-boxed phases, hard
stopping at their own limit regardless of completion — report status, don't
silently run over:

- **Feature (spec + task assignment)**: 30 min
- **Development**: 45 min
- **Testing**: 30 min

Also folds in 2 bugs found during analysis: `PER_TENANT_MAX_ACTIVE_CHAT` never
enforced (`services/chat_queue.py`), and `ENABLE_ASYNC_CHAT_QUEUE` flag has no
defined flip criteria.

## Phase 1 — Feature (architect)
- [x] Detailed feature spec covering all 5 points — see "PHASE 1 OUTPUT" below.
      All open questions resolved as explicit numbered decisions D1–D9, each
      with rationale, none deferred to founder mid-timebox.
- [x] Both bug fixes folded in as first-class scope: Bug 1 = D9 (Track A,
      dispatched FIRST, not last); Bug 2 = D7's flip criteria (Track B).
- [x] Concrete task assignment: 3 tracks (A/B/C), file-by-file, with ordering,
      a parallelisation ruling, and explicit do-not-touch boundaries — see
      "TASK ASSIGNMENT" below.
- [x] Spec destination chosen and stated: **new `feature_26_chat_attached_documents.md`
      under `Prod_Invoice_LLM/apps/invoice-be/docs/`**, NOT an addition to
      `docs/phase_2_enhancements.md`. Reason: that file states its own rule in
      its header — "Each item below gets its own `feature_N_*.md` spec when it's
      actually scoped — this document is the index, not the design." Fresh
      collision check 2026-09-01: max BE feature = 25
      (`feature_25_plug_and_play_workflows.md`), max FE feature = 18
      (`feature_18_desktop_app.md`), plus consolidated `feature_20_23_24_*`.
      26 is free. FE surface goes as an **additive section** into the existing
      `apps/invoice-fe/docs/feature_5_chat.md` (hard rule 4: additive only),
      not a new FE feature number.
      ROLE BOUNDARY, stated rather than silently worked around: architect does
      not author spec docs (CONVENTIONS.md — spec docs are senior-dev-owned,
      "architect never writes code or docs"). The full spec body is written out
      below and landing it at that path is **Track C task C0**.
- [x] Status line + timestamp — bottom of file.

## Phase 2 — Development (senior-dev)
- [ ] Implement per Phase 1's exact scope, in the order Phase 1 specified.
- [ ] Both bug fixes included.
- [ ] Narrow tests per this repo's own convention as each piece lands.
- [ ] Tracker Gap(s) filed per the no-code-without-gap rule.
- [ ] Status line + timestamp, explicit about anything not completed if the
      45-minute limit is hit.

## Phase 3 — Testing (functional-tester)
- [ ] Verify what Phase 2 actually shipped, against Phase 1's spec.
- [ ] Real evidence — Postgres run per hard rule 2, not SQLite-only.
- [ ] Coverage map updated.
- [ ] Status line + timestamp, explicit about anything not completed if the
      30-minute limit is hit.

## Orchestration notes (for the session managing this, not the agents)
Status emailed to sbanerji@admsofttech.com every 15 minutes, covering ALL
THREE areas' current status each time (not just whichever phase is active).
Each phase hard-stops at its own limit — if hit, report exactly what's done/
not done for that phase and move to founder review rather than extending
silently.

---

# PHASE 1 OUTPUT — spec + decisions

Gap numbering: max Gap across all three trackers = **363** (BE tracker; FE 358,
website 351 — numbers are globally unique across trackers in practice). Next
free = **364**. Assignments: Gap 364 = Track A, Gap 365 = Track B, Gap 366 =
Track C. File the Gap in the SAME change as the code (no-code-without-gap).

## Decisions — the scan list

**D1 — Which document types ship in v1? PO + Quotation only.**
Reconciliation statements, delivery challans and e-way bills are DEFERRED.
Why: the analysis confirmed a PO/quotation shares the existing
`InvoiceExtractionSchema` spine (party / doc number / date / line items /
subtotal / tax / total / currency / `po_number`, extraction_agent.py L110-134),
so it is a third `_DirectionProfile`, not a new pipeline. A reconciliation
statement is a multi-invoice ledger — different schema AND a different
comparison algorithm. Not a 45-minute lift.

**D2 — Persisted first-class, or session-scratch? First-class row in a NEW
`ChatAttachment` table. Never an `Invoice` row.**
Why: session-scratch breaks two paths that already exist — the FE reload/
reattach path (`useChatSession.ts` L232-241) and the async worker path, which
runs in a different process from the request. Writing an `Invoice` row instead
would silently corrupt spend aggregates, `/dashboard/insights`,
AUDIT_REQUIRED counts, billing quota and the RAG index. A quotation is not a
payable.

**D3 — Does it consume ingestion quota? No ingestion quota; yes chat metering.**
Plus hard caps: PDF-only, 10 MB per file, max 5 attachments per session.
Why: `billing_quota` meters invoice ingestion; a reference doc never becomes a
payable, so charging it misprices the plan. The turn is already metered where
chat is metered (`charge_sandbox_chat_or_402`, routers/chat.py L379) — leave
that alone. Caps are the abuse control instead of quota. PDF-only is
deliberate: image upload is `phase_2_enhancements.md` §2, a separate item.

**D4 — Point 2 matching strategy: confirmed as the analysis recommended, with
one revision on mechanism.**
Tier 1 deterministic normalised `po_number` join; Tier 2 fallback only if Tier
1 is empty (vendor-name substring match AND `invoice_date` within ±90 days of
the document date, capped at 20 candidates); explicit user confirmation of the
matched set before any financial answer — never a silent match.
REVISION: **no 4th value on the route enum.** Adding `"DOC"` to
`QueryRoutingSchema.route` (L102) does not work, because the `_SQL_KEYWORDS`
fast path (L131) contains "vendor"/"po number"/"purchase order"/"total" and
pre-empts the classifier before any LLM call — an attached-PO question would
route to SQL and silently drop the attachment. Instead: a **deterministic
pre-route gate** — if the request carries an `attachment_id`,
`_run_query_agent` enters the attached-document branch and `classify_query()`
is never called. Zero LLM involvement in the routing decision, and it sidesteps
both the closed enum and the keyword fast path.

**D5 — Hard rule 3 (discrepancy math must be deterministic): satisfied by a new
`services/document_comparison.py::compare_reference_to_invoices()` — pure
Python, `Decimal` arithmetic, no LLM anywhere in the module.**
The LLM receives the already-computed diff table and narrates it only.
Why: hard rule 3 is non-negotiable and Gaps 220-225/253 are the precedent. The
pattern is already in-repo — Feature 18's `_normalize_for_diff` /
`_DIFFABLE_FIELDS` (routers/chat.py L850-880) already does a deterministic
value diff that includes `po_number` and `grand_total`. Reuse that shape rather
than inventing a second one. A currency mismatch is a hard stop, not a diff
row. The synthesis prompt explicitly forbids stating any number not present in
the diff table.
NOTE the analysis's related warning: `_normalize_string_equality()`
(query_agent.py L247-294) is a regex rewriter over LLM-written SQL, and Gap 253
killed exactly that class of thing. This design does not extend it — matching
is a parameterised ORM/SQL query written by us, not a rewrite of model output.

**D6 — Point 3 suggested actions: confirmed as scoped. Deep-links to existing
endpoints ONLY; no new flag/dispute/hold/escalate/snooze/assign workflow. And
suggest, never execute — chat never calls a mutating endpoint.**
Why: the analysis confirmed none of those routes exist anywhere; building one
is net-new backend surface plus RBAC plus an audit trail. The deep-link half
has a working in-repo precedent (`ThumbsDownTriage.tsx` L729-731 consuming
`triage_source_verdict()`'s `redirect` block; `CitationPill.tsx` L37-38).
Suggestions come from a **deterministic map** keyed on (diff outcome,
`invoice.status`, `flow_direction`) — not LLM-chosen — because the real
endpoints have legal-transition rules (outbound confirm-send only from
VERIFIED/NEEDS_REVIEW, mark-paid only from SENT) that an LLM would violate.
Copy must respect the two semantics the analysis flagged: OVERDUE is computed
at read time and never written; inbound AUDIT_REQUIRED means a math/data flag,
not unpaid.

**D7 — Point 4 flip criteria (this IS the Bug 2 fix): 5 concrete testable
criteria, all required, then a dev-only flip; prod stays False until a 24h dev
soak with zero orphaned `chat_inflight` counters.**
Why: the flag docstring (config.py L26-31) says flip "once the path has real
live evidence" but never says what evidence — undefined criteria is the bug.
Evidence must come from a Postgres + real Redis run (hard rule 2).
1. An SSE transcript from one real turn shows **≥6 distinct `step` events**
   (today it publishes exactly 2, hardcoded, handlers.py L1019-1042).
2. A 4th concurrent job for one tenant returns **429**, and the 3 in flight all
   complete.
3. A narrowing follow-up sent while the prior turn is in flight **still routes
   to SQL** (Gap 237 override intact) — proves D8's per-session serialisation.
4. A **failed** job releases its slot: `chat_inflight:{tenant}` returns to 0
   after `fail_job`.
5. With Redis unreachable, `POST /sessions/{id}/message` still answers via the
   sync path — no 500.
These five get written into the `config.py` L26-31 docstring as part of Track
B. That is the deliverable — not a comment somewhere else.

**D8 — Point 5 parallel vs queued: serialise per SESSION, allow parallelism
ACROSS sessions (up to `PER_TENANT_MAX_ACTIVE_CHAT`).**
This is a deliberate sharpening of the analysis's queued-in-order lean, not an
override of it. Why: the correctness risk is real but its scope is exactly one
session — `_previous_assistant_sql()` (L2766) and `_is_narrowing_followup()`
(L210, used at L2871) read the previous turn *in this session*. Two turns in
different sessions cannot race that. Global serialisation would throw away the
concurrency the queue was built for in order to fix a per-session bug.
Bonus, and it is why this is the pragmatic MVP call: it **removes the FE work**
— the single `activeStreamRef` (useChatSession.ts L41) is correct under
per-session serialisation, so no listener map is needed in v1.

**D9 — Bug 1 rejection behaviour: reject with HTTP 429 + `Retry-After: 5`, not
queue-instead-of-reject.**
Why: the Redis list already IS the queue; an unbounded second queue moves
latency without bounding it and defeats the noisy-neighbour purpose the
constant was written for. 429 is honest backpressure and the FE already has an
error surface.

## Spec body — content for `feature_26_chat_attached_documents.md`

### File Coordinates
**BE, new:** `models.py::ChatAttachment` (id, tenant_id, session_id, filename,
blob_path, doc_type, extracted_json, doc_number, party_name, doc_date,
currency, grand_total, confirmed_invoice_ids, created_at);
`routers/chat_attachments.py` (NEW router — deliberately NOT inside
`routers/chat.py`, see boundaries); `services/document_comparison.py`
(`compare_reference_to_invoices()`, `find_candidate_invoices()`,
`normalize_doc_number()`, `build_suggested_actions()`).

**BE, modified:** `agents/extraction_agent.py` — third `_DIRECTION_PROFILES`
entry `"REFERENCE"` plus `ReferenceDocExtractionSchema` (the L110-134 spine plus
`doc_type` as PURCHASE_ORDER/QUOTATION/OTHER), `required_fields=()`,
`passed_status="EXTRACTED"`, `review_status="EXTRACT_FAILED"`,
`legacy_audit_path_shim=False`; `agents/query_agent.py` (attachment param plus
pre-route gate); `queue_worker/handlers.py`; `config.py`;
`services/chat_queue.py`; `routers/chat.py` (Track A only).

**FE, modified:** `components/chat/ChatWindow.tsx` (InputBar is co-located at
L352-437, not its own file — paperclip plus hidden file input, lifting
`components/ingestion/DropZone.tsx`'s guards: pdf accept L121, size cap L22,
suffix guard L58); `types/chat.ts` (L52-76 has no attachment field today);
`hooks/useChatSession.ts` (send attachment_id); new
`components/chat/AttachmentMatchConfirm.tsx`.

### Functionality — the flow end to end
1. User clicks the paperclip in the chat composer, picks a PDF (max 10 MB, max
   5 per session).
2. POST /chat/sessions/{id}/attachments writes the blob at
   `chat-attachments/{tenant_id}/{attachment_id}.pdf`, creates the
   `ChatAttachment` row, runs `run_extraction_agent(flow_direction="REFERENCE")`
   synchronously, updates the row. Returns doc_type, doc_number, party_name,
   grand_total, currency.
3. User asks a question with attachment_id on the message. The pre-route gate
   fires; `classify_query()` is skipped entirely (D4).
4. `find_candidate_invoices()` runs Tier 1 (normalised po_number exact match)
   and only if empty, Tier 2 (vendor substring plus 90-day window, cap 20).
5. Confirmation turn. If the attachment has no confirmed_invoice_ids yet, the
   assistant returns a match-confirmation payload — never an answer. The user
   confirms via POST /chat/attachments/{id}/confirm-matches, which writes
   confirmed_invoice_ids so follow-ups reuse the set without re-asking. Zero
   matches means say so plainly and offer manual invoice-number entry; never
   guess.
6. Answer turn. `compare_reference_to_invoices()` produces the deterministic
   diff; the LLM narrates that table and nothing else (D5).
7. `build_suggested_actions()` returns 0-3 deep-links from the deterministic
   map. Rendered as links. Never auto-invoked (D6).

### Verification Plan (design intent; the live record goes in the coverage map)
Deterministic-comparison unit tests must pass on exact-match, over-billed,
under-billed, extra-line, missing-line, currency-mismatch and empty-candidate
cases. Tenant isolation: tenant B cannot read or match against tenant A's
attachment. Confirmation gate: an answer turn issued before confirmation must
return the confirmation payload, not a number.

---

# TASK ASSIGNMENT

## Parallelisation ruling
**A and B are safe to run concurrently — zero shared files.** C must run AFTER
B: both edit `agents/query_agent.py` and `queue_worker/handlers.py`, and B
changes the `run_query_agent` signature that C's gate sits inside. C was
deliberately scoped so its endpoints live in a NEW
`routers/chat_attachments.py`, which is also what keeps A and C conflict-free.
Recommended dispatch inside the 45-min dev budget: A and B in parallel now
(~10 and ~15 min), C after B. If the clock binds, C ships BE-only (C0-C5) with
the FE slice (C6) explicitly deferred rather than half-built.

## TRACK A — senior-dev — Bug 1: enforce PER_TENANT_MAX_ACTIVE_CHAT (Gap 364)
**Files:** `services/chat_queue.py`, `routers/chat.py`,
`tests/test_chat_queue.py`, `docs/be_features_tracker.md`.
- A1. `enqueue_chat_job()` (L42-93): make the counter a real limiter. Atomic
  INCR first, compare against `PER_TENANT_MAX_ACTIVE_CHAT` (L21); if over,
  DECR back and raise a new typed `ChatQueueCapacityError`. Today L79
  increments and never compares — the constant is referenced nowhere else in
  the application.
- A2. Fix the slot leak in the same function: the `except` at L90-91 currently
  swallows a failed `lpush` that happens AFTER the INCR at L79, leaking a slot
  permanently. Roll the counter back on that failure path.
- A3. `routers/chat.py::post_chat_message` L412-418: catch
  `ChatQueueCapacityError` and return HTTP 429 with `Retry-After: 5` and a JSON
  detail. Do not write the ChatMessage row until enqueue succeeds (preferred)
  so a rejected turn leaves no orphan `queued` row.
- A4. Correct the stale tracker claim at `be_features_tracker.md` L897, which
  asserts this limit already works. Same Gap 364 entry. Direct precedent: Gap
  352 was this same class of defect — a declared meter that did not meter.
- A5. Narrow test only, `tests/test_chat_queue.py`: 4th enqueue rejected, 3 in
  flight unaffected, slot released on `fail_job`, counter rolled back when
  lpush fails.

**Out of scope / do not touch:** the sync chat path (it never touches the
counter — note that limitation in the Gap, do not fix it here),
`agents/query_agent.py`, `queue_worker/handlers.py`, any FE file, and the value
3 itself.

## TRACK B — senior-dev — Point 4 live progress + Bug 2 flip criteria (Gap 365)
**Files:** `agents/query_agent.py`, `queue_worker/handlers.py`, `config.py`,
`tests/test_chat_queue.py` (or a new `tests/test_chat_progress.py`).
- B1. Add an optional `on_progress` callback parameter (step string, optional
  details dict) to `run_query_agent` (L2742) and `_run_query_agent` (L2782).
  Default None means no-op, so every existing caller keeps working unchanged —
  including `agents/query_tools.py::query_invoices()`.
- B2. Publish at these NINE seams (the analysis estimated 8-10):
  (1) classify_query start; (2) route decided — include the Gap 237 override at
  L2871 so an overridden route is visible; (3) cache-hit shortcut at L2795;
  (4) SQL prompt build (L2908); (5) EACH attempt of `run_sql_generation_loop`
  (max_attempts=3, L2922) with the attempt number in details — this is the seam
  users actually wait on; (6) SQL execution; (7) summary synthesis; (8) RAG
  retrieve; (9) RAG rerank.
- B3. `queue_worker/handlers.py` L1019-1042: replace the 2 hardcoded steps with
  the callback wired to `ChatQueueService.publish_progress`. Mirror the shape
  ingestion already uses at L594-600 — that is the in-repo blueprint, do not
  invent a second one. The `graph.stream()` trick does NOT transfer:
  `run_query_agent` is a plain imperative function, not a LangGraph.
- B4. Rewrite the ENABLE_ASYNC_CHAT_QUEUE docstring (`config.py` L26-31) with
  D7's 5 flip criteria verbatim. LEAVE THE VALUE False — flipping it is
  functional-tester's evidence-gated call in Phase 3, not senior-dev's.
- B5. D8 per-session serialisation: a Redis lock keyed
  `chat_session_lock:{session_id}` held by the worker for the turn's duration; a
  second turn for the same session waits rather than running concurrently.
  Cross-session parallelism unchanged.
- B6. Narrow test: one turn emits at least 6 distinct steps; two same-session
  turns serialise; two different-session turns do not.

**Out of scope / do not touch:** `services/chat_queue.py` (Track A owns it —
`publish_progress` L95-131 is already correct as-is), `routers/chat.py`, any FE
file, flipping the flag, and `telemetry.py`/`tracked_llm_call` (customEvents is
a separate channel — do not merge the two).

## TRACK C — senior-dev — attached-document grounding (Gap 366) — AFTER Track B

**TRACK C STATUS (2026-09-01, 30-min box): C0–C5 DONE, C6 NOT STARTED (the pre-agreed cut line).** Backend complete and tested (tests/test_chat_attachments.py → 22 passed; +32 Track A/B regression = 54 passed). Gap 366 filed in be_features_tracker.md as [~]. FE surface specified as an additive section in apps/invoice-fe/docs/feature_5_chat.md but not built.
- C0. Write `apps/invoice-be/docs/feature_26_chat_attached_documents.md` from
  the spec body above (File Coordinates / Functionality / Tasks / Verification
  Plan). Do this FIRST — it is the artifact functional-tester verifies against.
- C1. `models.py::ChatAttachment` plus an Alembic migration
  (`feature_12_alembic.md` is the convention).
- C2. `agents/extraction_agent.py`: `ReferenceDocExtractionSchema` plus the
  "REFERENCE" profile. ADDITIVE ONLY — do not alter the INBOUND/OUTBOUND
  profiles (L406-427) or `resolve_direction_profile`'s existing behaviour.
- C3. NEW `routers/chat_attachments.py`: POST /chat/sessions/{id}/attachments
  (PDF-only, 10 MB, max 5 per session, tenant-checked the way
  `_require_owned_chat_job` L595-646 does it — Gap 341's pattern), POST
  /chat/attachments/{id}/confirm-matches, GET /chat/attachments/{id}. Register
  in `main.py`.
- C4. NEW `services/document_comparison.py` — deterministic, Decimal, no LLM
  anywhere in the module. Model it on `_normalize_for_diff` / `_DIFFABLE_FIELDS`
  (routers/chat.py L850-880). Includes `build_suggested_actions()`'s
  deterministic map over the real endpoints only: PUT /audit/resolve/{id}
  (statuses limited to PAID / REJECTED / AUDIT_REQUIRED, routers/audit.py L395),
  outbound confirm-send (VERIFIED or NEEDS_REVIEW only, L216-220), mark-paid
  (SENT only, L272-276), outbound-audit resolve (never changes status),
  soft-delete (routers/invoices.py L791), batch rollback (L669), open-in-Trainer
  (routers/trainer.py L785).
- C5. `agents/query_agent.py`: attachment_id parameter plus the pre-route gate
  BEFORE `classify_query()`. Confirmation-first: no confirmed_invoice_ids means
  return the confirmation payload, never a computed answer.
- C6. FE (defer this first if the clock runs out): paperclip plus hidden file
  input in `ChatWindow.tsx`'s InputBar (L352-437) lifting `DropZone.tsx`'s
  guards; attachment field on `types/chat.ts`; `useChatSession.ts` sends
  attachment_id; new `AttachmentMatchConfirm.tsx`. Additive section into
  `apps/invoice-fe/docs/feature_5_chat.md`.

**Out of scope / do not touch:** reconciliation statements, delivery challans,
e-way bills (D1); any non-PDF format — that is `phase_2_enhancements.md` section
2, a different item; writing Invoice rows or touching billing quota (D3);
RAG/Chroma metadata — `query_invoice_chunks()` passes no where-filter and chunk
metadata has no po_number, so PO lookup is SQL-side and there is nothing to
re-index; `services/invoice_reconciliation.py` — MISLEADING FILENAME, it is a
stuck-queue sweep and has nothing to do with this; any new
flag/dispute/hold/escalate route (D6); executing any mutating endpoint from
chat; `components/trainer/TrainerUploader.tsx` (dead code, do not revive).

## PHASE 3 — functional-tester (dispatch after Phase 2 reports)
Postgres plus real Redis, per hard rule 2. No SQLite-only claim is acceptable.
- T1. Track A: enqueue 4 concurrent jobs for one tenant — 4th returns 429 with
  Retry-After, the other 3 complete; `chat_inflight` returns to 0 after both
  completion and failure; no orphan `queued` ChatMessage row after a 429.
  Confirm tracker L897 now matches the code.
- T2. Track B: capture a real SSE transcript from GET /chat/jobs/{id}/stream —
  assert at least 6 distinct steps and that SQL retry attempts are individually
  visible. Same-session turns serialise; cross-session turns do not. A narrowing
  follow-up still routes to SQL under load (Gap 237 intact).
- T3. Track C: upload a PO PDF; assert the ChatAttachment row and blob exist,
  and assert NO Invoice row was created and no billing-quota counter moved.
  Tier 1 PO match, Tier 2 fallback, zero-match path. Confirmation gate: an
  answer turn before confirmation returns the confirmation payload, not a
  number. Tenant isolation on all three new endpoints.
- T4. Flip decision on ENABLE_ASYNC_CHAT_QUEUE: evaluate all 5 of D7's criteria
  and report pass/fail per criterion. Flip in dev only if all 5 pass; otherwise
  report which failed and leave it False.
- T5. Update `apps/invoice-be/docs/test_coverage_map.md`; raw evidence into
  `test_evidence/`.

**Out of scope:** fixing anything found — file it back, do not patch it.

## Flags for the founder (not blocking, but stated)
1. `active-work.md` L18 freezes "SAGE Phase 3 — do not touch", pointing at a
   deleted `feature_21_sage.md`. This build is Phase 2, not Phase 3, and was
   explicitly founder-approved today — proceeding on that basis. The stale
   pointer still needs reconciling.
2. Priority-order check (CONVENTIONS.md): this is coding plus functional
   testing — steps 1 and 2. Correctly ordered, no jump-ahead.
3. Track C is the largest piece and comes last. If 45 minutes binds, the likely
   real outcome is A and B complete with C partial. That ordering is deliberate:
   the two bugs are shipped correctness defects, the attachment feature is new
   surface.

**FINAL STATUS (2026-09-01): Phase 1 DONE, inside the 30-minute budget.** All 5
analysis points resolved into 9 stated decisions (D1-D9), both bugs folded in as
Track A and Track B scope items rather than afterthoughts, 3 task tracks
assigned file-by-file with a parallelisation ruling and explicit do-not-touch
boundaries, Phase 3 test plan written, and the spec destination chosen after a
fresh collision check (BE feature 26 is free). Nothing outstanding. One role
boundary carried openly rather than worked around: the spec doc body is written
here and lands at its real path as senior-dev's task C0, because architect does
not author spec docs under CONVENTIONS.md.
