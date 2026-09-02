# Feature 26 — Chat Attached Documents (PO / Quotation grounding)

Status lives in `docs/be_features_tracker.md` (Gap 366). This document is the
durable design record; the working-state tasklist that produced it
(`.claude/tasklists/architect-phase2-sage-feature-build.md`, Phase 1 output) is
not the record and may be cleaned up.

Collision check at creation time (2026-09-01): max BE feature was 25
(`feature_25_plug_and_play_workflows.md`), max FE feature 18 plus the
consolidated `feature_20_23_24_ops_workbook.md`; 26 was free. Max Gap across all
three trackers was 365 (Tracks A/B took 364/365 the same day); 366 was free.

## Overview

Today chat can only talk about invoices the tenant has *ingested*. A user
holding the purchase order or the quotation that an invoice was supposed to
match has no way to ask "does this bill agree with what we agreed?" — they have
to eyeball two PDFs.

This feature lets a user attach a **PO or a quotation** to a chat session, and
then ask a question grounded in that document. The system extracts the attached
document, deterministically finds the invoice(s) it plausibly corresponds to,
**asks the user to confirm the match before it says anything financial**, and
then reports a diff computed in pure Python — the LLM narrates that table and is
forbidden from producing a number that is not in it.

### What this is NOT

- **Not an invoice.** An attached PO or quotation never becomes an `Invoice`
  row (D2). It is not a payable, does not enter spend aggregates,
  `/dashboard/insights`, AUDIT_REQUIRED counts, the RAG index, or billing quota.
- **Not a new ingestion pipeline.** It is a third `_DirectionProfile` on the
  existing extraction graph (D1).
- **Not a new route value.** The chat router enum stays
  `Literal["RAG","SQL","CHAT"]`; attachment handling is a deterministic
  pre-route gate (D4).
- **Not a dispute/flag/hold workflow.** Suggested actions deep-link to endpoints
  that already exist; chat never calls a mutating endpoint (D6).

## Design record — decisions D1–D6

These were resolved before implementation and are recorded here rather than left
in working state.

### D1 — Which document types ship in v1? PO + Quotation only.

Reconciliation statements, delivery challans and e-way bills are deferred. A
PO/quotation shares the existing `InvoiceExtractionSchema` spine (party / doc
number / date / line items / subtotal / tax / total / currency / `po_number`,
`agents/extraction_agent.py` L110–134), so it is a third `_DirectionProfile`,
not a new pipeline. A reconciliation statement is a multi-invoice ledger —
different schema *and* a different comparison algorithm. Out of budget, and out
of scope here.

PDF-only. Image upload is `docs/phase_2_enhancements.md` §2 — a separate item,
deliberately not folded in.

### D2 — Persisted first-class, never an `Invoice` row.

A new `ChatAttachment` table. Session-scratch was rejected because it breaks two
paths that already exist: the FE reload/reattach path
(`useChatSession.ts` L232–241) and the async worker path, which runs in a
different process from the request. Writing an `Invoice` row instead would
silently corrupt spend aggregates, `/dashboard/insights`, AUDIT_REQUIRED counts,
billing quota and the RAG index. A quotation is not a payable.

### D3 — No ingestion quota; chat metering only. Plus hard caps.

`billing_quota` meters invoice ingestion; a reference doc never becomes a
payable, so charging it misprices the plan. The turn is already metered where
chat is metered (`charge_sandbox_chat_or_402`, `routers/chat.py`) — that is left
alone. The abuse control is caps instead: **PDF-only, 10 MB per file, max 5
attachments per session**, enforced in the upload service path
(`routers/chat_attachments.py`) — see "Cap enforcement" below for exactly where.

### D4 — Matching strategy, and the routing mechanism.

Matching:
- **Tier 1** — deterministic normalised `po_number` exact join against `Invoice`
  rows of the same tenant.
- **Tier 2** — fallback *only if Tier 1 returned empty*: vendor-name substring
  match **and** `invoice_date` within ±90 days of the attached document's date,
  capped at 20 candidates.
- **Explicit user confirmation of the matched set before any financial answer.**
  Never a silent match on financial data.

Routing mechanism, revised from the initial sketch: **no 4th value on the route
enum.** Adding `"DOC"` to `QueryRoutingSchema.route` does not work, because the
`_SQL_KEYWORDS` fast path (`agents/query_agent.py` L191, checked at L226)
contains "vendor" / "po number" / "purchase order" / "total" and pre-empts the
classifier before any LLM call — an attached-PO question would route to SQL and
silently drop the attachment. Instead: a **deterministic pre-route gate**. If
the request carries an `attachment_id`, `_run_query_agent()` enters the
attached-document branch and `classify_query()` is never called. Zero LLM
involvement in the routing decision; sidesteps both the closed enum and the
keyword fast path.

### D5 — Discrepancy math is deterministic (hard rule 3).

`services/document_comparison.py::compare_reference_to_invoices()` is pure
Python with `Decimal` arithmetic and **no LLM anywhere in the module**. The LLM
receives an already-computed diff table and narrates it only.

The pattern is already in-repo: Feature 18's `_normalize_for_diff` /
`_DIFFABLE_FIELDS` (`routers/chat.py` L884–913) already does a deterministic
value diff that includes `po_number` and `grand_total`. This module reuses that
shape rather than inventing a second one.

**A currency mismatch is a hard stop, not a diff row.** If the attached document
is in a different currency from a candidate invoice, that candidate's comparison
is refused outright with `outcome="currency_mismatch"` — the module does not
convert, does not compare magnitudes, and does not silently ignore it. Comparing
150 EUR against 150 INR as "a match" is exactly the class of wrong answer this
feature exists to prevent.

Related warning carried forward: `_normalize_string_equality()`
(`agents/query_agent.py` L247–294) is a regex rewriter over LLM-written SQL, and
Gap 253 killed exactly that class of thing. This design does **not** extend it —
matching is a parameterised ORM query written by us, not a rewrite of model
output.

### D6 — Suggested actions: deep-links to existing endpoints only, suggest never execute.

None of a flag/dispute/hold/escalate/snooze/assign route exists anywhere in the
codebase; building one is net-new backend surface plus RBAC plus an audit trail.
The deep-link half has a working in-repo precedent (`ThumbsDownTriage.tsx`
consuming `triage_source_verdict()`'s `redirect` block; `CitationPill.tsx`).

Suggestions come from a **deterministic map** keyed on (comparison outcome,
`invoice.status`, `flow_direction`) — not LLM-chosen — because the real
endpoints have legal-transition rules that an LLM would violate:

| Target | Precondition actually enforced by the endpoint |
|---|---|
| `PUT /api/v1/audit/resolve/{id}` | inbound; resolution status must be PAID / REJECTED / AUDIT_REQUIRED |
| outbound confirm-send | status VERIFIED or NEEDS_REVIEW only |
| outbound mark-paid | status SENT only |
| outbound-audit resolve | never changes status |
| open in Trainer | always legal (read-only destination) |

`build_suggested_actions()` checks the precondition before emitting the link, so
a suggestion is never one the endpoint would reject. Copy respects two semantics
that are easy to get wrong: **OVERDUE is computed at read time and never
written**, and inbound **AUDIT_REQUIRED means a math/data flag, not unpaid**.

Chat never invokes any of these. It returns links.

## File Coordinates

**BE, new**
- `models.py::ChatAttachment` — `id`, `tenant_id`, `session_id`, `filename`,
  `blob_path`, `doc_type`, `file_size_bytes`, `extraction_status`,
  `extracted_json`, `doc_number`, `party_name`, `doc_date`, `currency`,
  `grand_total`, `candidate_invoice_ids`, `confirmed_invoice_ids`, `created_at`.
- `alembic/versions/c2d3e4f5a6b7_add_chat_attachments.py` — creates
  `chatattachment`, down_revision `b1c2d3e4f5a6`.
- `routers/chat_attachments.py` — `POST /chat/sessions/{id}/attachments`,
  `POST /chat/attachments/{id}/confirm-matches`, `GET /chat/attachments/{id}`.
  Deliberately a separate module from `routers/chat.py`.
- `services/document_comparison.py` — `normalize_doc_number()`,
  `find_candidate_invoices()`, `compare_reference_to_invoices()`,
  `build_suggested_actions()`, `build_confirmation_payload()`.

**BE, modified**
- `agents/extraction_agent.py` — `ReferenceDocExtractionSchema`,
  `_build_reference_multimodal_prompt`, `_build_reference_text_prompt`, and a
  third `_DIRECTION_PROFILES` entry `"REFERENCE"`. Additive only; INBOUND and
  OUTBOUND profiles and `resolve_direction_profile()`'s behaviour are untouched.
- `agents/query_agent.py` — `attachment_id` parameter on `run_query_agent()` /
  `_run_query_agent()` (default `None`, every existing caller unaffected) plus
  the pre-route gate, and `_run_attached_document_turn()`.
- `routers/chat.py` — `MessageCreate.attachment_id: UUID | None = None`,
  `run_sync_chat_turn(..., attachment_id: str | None = None)` passing it into
  `run_query_agent()`, and `post_chat_message()` supplying it. Parameter
  threading only — no new endpoint and no new logic in that file.
- `main.py` — router registration.

**FE, modified** (additive section in `apps/invoice-fe/docs/feature_5_chat.md`)
- `components/chat/ChatWindow.tsx` — the composer's InputBar is co-located in
  this file, not its own module; paperclip + hidden file input lifting
  `components/ingestion/DropZone.tsx`'s guards (PDF accept, size cap, suffix
  guard).
- `types/chat.ts`, `hooks/useChatSession.ts`.

## Functionality — the flow end to end

1. User clicks the paperclip in the chat composer and picks a PDF (max 10 MB,
   max 5 per session).
2. `POST /api/v1/chat/sessions/{id}/attachments` writes the blob under
   `tenants/{tenant_id}/chat-attachments/{attachment_id}.pdf`, creates the
   `ChatAttachment` row, then runs
   `run_extraction_agent(flow_direction="REFERENCE")` synchronously and updates
   the row. Returns `doc_type`, `doc_number`, `party_name`, `grand_total`,
   `currency`.
3. The user asks a question with `attachment_id` on the message. The pre-route
   gate fires in `_run_query_agent()`; `classify_query()` is skipped entirely
   (D4) — no LLM is consulted about routing.
4. `find_candidate_invoices()` runs Tier 1 (normalised `po_number` exact match)
   and, only if empty, Tier 2 (vendor substring + ±90-day window, cap 20).
5. **Confirmation turn.** If the attachment has no `confirmed_invoice_ids` yet,
   the assistant returns a match-confirmation payload — never an answer. The
   user confirms via `POST /api/v1/chat/attachments/{id}/confirm-matches`, which
   writes `confirmed_invoice_ids` so follow-ups reuse the set without re-asking.
   Zero matches means say so plainly and offer manual invoice-number entry;
   never guess.
6. **Answer turn.** `compare_reference_to_invoices()` produces the deterministic
   diff; the LLM narrates that table and nothing else (D5). A currency mismatch
   short-circuits to a refusal for that invoice.
7. `build_suggested_actions()` returns 0–3 deep-links from the deterministic
   map. Rendered as links. Never auto-invoked (D6).

### Cap enforcement — where, concretely

D3's caps are enforced in the request path, not by a DB constraint, because two
of the three are inherently request-shaped:

- **PDF-only** — filename suffix + `content_type` check before any bytes are
  persisted.
- **10 MB** — measured on the actual read bytes (not the client's
  `Content-Length`, which is attacker-controlled), rejected with 413.
- **5 per session** — `SELECT count(*)` over the session's existing rows inside
  the same request, rejected with 409.

`file_size_bytes` is persisted on the row so the cap is auditable after the fact
rather than only being a transient check.

## Tasks

- [x] C0 — this spec doc + additive FE section in `feature_5_chat.md`.
- [x] C1 — `models.py::ChatAttachment` + Alembic migration.
- [x] C2 — `ReferenceDocExtractionSchema` + `"REFERENCE"` direction profile.
- [x] C3 — `services/document_comparison.py`.
- [x] C4 — pre-route gate in `_run_query_agent()`.
- [x] C5 — `routers/chat_attachments.py` + `main.py` registration.
- [x] C5b — `routers/chat.py` wiring (2026-09-01, closing Gap 366's own stated
  scope rather than a new gap). C4 gave the agent an `attachment_id`; until this
  step nothing supplied one, because `POST /chat/sessions/{id}/message` — the
  endpoint every real chat turn goes through — had no such field on its request
  body, so the feature was reachable only by calling `run_query_agent()`
  directly. `MessageCreate` gained the optional field, `run_sync_chat_turn()`
  gained a matching keyword and passes it to `run_query_agent()`, and
  `post_chat_message()` supplies it (`str(...)` at the boundary, since the agent
  signature is `Optional[str]`). **Async path**: deviation from "thread it
  through both paths" stated rather than hidden — `use_async_queue` now also
  requires `payload.attachment_id is None`, so an attached-document turn runs
  synchronously. The queue carries only (session_id, user_msg_id, content,
  tenant_id, job_id); enqueuing an attachment turn would drop the attachment and
  answer it as an ordinary chat turn, which is the same silent-drop failure the
  pre-route gate exists to prevent. Carrying it through the worker means
  changing `services/chat_queue.py` and `queue_worker/handlers.py` and needs its
  own gap. Tests: 2 router-level tests in `tests/test_chat_attachments.py`
  asserted on the `_run_attached_document_turn` mock plus
  `classify_query.assert_not_called()`; file → 24 passed,
  `tests/test_chat_queue.py` → 19 passed.
- [ ] C6 — FE composer attachment button. See status note at the bottom.

## Verification Plan

Design intent; the live record of what is actually automated goes in
`docs/test_coverage_map.md`, not here.

- **Deterministic comparison** unit tests on exact-match, over-billed,
  under-billed, extra-line, missing-line, currency-mismatch and empty-candidate
  cases.
- **Tier 1 vs Tier 2**: a matching `po_number` must return via Tier 1 and must
  *not* fall through to Tier 2; Tier 2 must fire only when Tier 1 is empty, must
  respect the ±90-day window, and must cap at 20.
- **Routing gate**: an `attachment_id` on the turn means `classify_query()` is
  never invoked — asserted by mocking `classify_query` and checking it was not
  called, not merely by checking the answer looked right.
- **Confirmation gate**: an answer turn issued before confirmation returns the
  confirmation payload, not a number.
- **Tenant isolation**: tenant B cannot read tenant A's attachment, cannot
  confirm matches on it, and cannot match against tenant A's invoices.
- **Non-effects**: uploading an attachment creates no `Invoice` row and moves no
  billing-quota counter (Postgres run, hard rule 2).

## Status note (2026-09-01)

Built in a 30-minute time-boxed track (Track C of the Phase 2 SAGE build), after
Tracks A (Gap 364) and B (Gap 365). Backend is complete through C5. C6 (the FE
composer control) was the pre-agreed cut line and its actual state is recorded
in the tracker's Gap 366 entry — backend-complete-with-no-UI was the accepted
hand-off shape; UI-with-no-backend was not.
</content>
</invoke>
