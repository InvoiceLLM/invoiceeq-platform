# FE Feature 21 / BE Feature 30 — Chat Attachment Insights — Local Stack + Real Azure AI

Local stack, real Azure Document Intelligence + real Azure OpenAI narration model
(`verdict_source: "model"` in the telemetry below — not the mock/template path).
BE + worker were **stopped and restarted** with `ENABLE_ATTACHMENT_INSIGHTS=true` for
this run only (previously unset). Not the deployed dev stack.

No fixture file existed at `apps/invoice-be/showcase/vpi_demo` (does not exist in this
checkout) or as a ready-made non-invoice financial-document PDF, so a synthetic
one-page Purchase Order PDF was generated with PyMuPDF
(`synthetic_po_attachment.pdf`, this dir): vendor "Infinevo Cloud Inc. (InvoiceEQ)"
(matches the real vendor name on seeded invoice `IEQ-US-9003`), PO total $10,000,
dated 2026-05-01 — deliberately less than `IEQ-US-9003`'s real grand_total ($12,000)
so a genuine overbilling finding would occur.

## Steps and commands

```
POST /api/v1/chat/sessions {"title":"F30 insights test"} -> 200, session 384ebdeb-...
POST /api/v1/chat/sessions/384ebdeb-.../attachments  (multipart, synthetic PO PDF)
  -> 200, extraction_status=PENDING, extraction_job_id=1d64e8c5-...
```

Polled `GET /api/v1/chat/attachments/{id}` until `extraction_status=EXTRACTED`
(real Azure DI OCR + real classification, confidence 1.00, doc_type=PURCHASE_ORDER,
doc_number=PO-2026-INV-9003, party_name="Infinevo Cloud Inc. (InvoiceEQ)").

## Real matching + insight pipeline (from worker log, `worker_log_insight_events.txt`)

Two `insight_bubble` telemetry events fired automatically (no explicit chat question
needed — the sync bubble posts as soon as extraction+matching finish, per the
feature's own design):
- `stage: "sync"`, `card_count: 10`, `finding_count: 1`, `impact_total: 2000.0`,
  `verdict_source: "template"`
- `stage: "async"`, `card_count: 10`, `finding_count: 2`, `impact_total: 12000.0`,
  `verdict_source: "model"`, `gate_status: "ok"` — **the real Azure OpenAI narration
  model ran and passed the answer-contract gate** (no hardcoded figure).

## DB (real Postgres)

```sql
SELECT candidate_invoice_ids, match_tier, match_summary FROM chat_attachments
WHERE id='50ddeed5-0d2f-4a1e-8396-8c5cc3186242';
```
`candidate_invoice_ids=[a2e6283d-...,9e76b498-...,9b029d53-...]`, `match_tier=2`,
`match_summary="probable match: IEQ-US-9003 (same party and date window)"` — Tier-2
vendor+date-window matching (the deterministic matcher, not the LLM) worked correctly.

```sql
SELECT role, content, attachment_payload FROM chatmessage
WHERE session_id='384ebdeb-...';
```
One assistant turn: *"Infinevo Cloud Inc. (InvoiceEQ) overbilled on IEQ-US-9003 by
$2,000.00 and $10,000.00 of this order has not been invoiced yet."* — arithmetically
exact ($12,000 billed - $10,000 agreed = $2,000 overbilled), with a full
`attachment_payload.insights` JSON: `what_this_is` and `agreed_vs_billed` cards, each
with figures, evidence and per-invoice comparison rows (3 invoices checked against the
PO — Tier-2 proposed all 3 same-vendor/date-window candidates).

## FE screenshots (Playwright, chromium, no route stubbing, DISABLE_CLERK_AUTH=true)

- `insight_bubble.png` — `/chat`, "F30 insights test" thread open: verdict headline,
  two findings each with a confidence chip ("Fairly sure — matched on party and date,
  not confirmed by you yet"), dollar figures ($2,000.00, $10,000.00), a "Not checked"
  section naming 4 skipped cards and why, and the action row: **Add a note**,
  **Discuss**, **Dismiss**, plus message-level and per-finding thumbs up/down icons.
- `discuss_chip.png` — after clicking **Discuss** on the first finding, the composer
  pre-filled with *"About this finding (USD 2,000.00): IEQ-US-9003 bills $2,000.00
  more than this purchase order agreed — what should I do?"* — confirmed working.

## Per-card thumbs (API-level, since the UI click target proved hard to isolate in headless Playwright)

```
POST /api/v1/chat/messages/661b84a5-.../insight-feedback
  {"card":"agreed_vs_billed","finding_key":"overbilled_IEQ-US-9003","vote":"down","reason":"wrong_figure"}
-> 200 {"correction_id":"619c9d8b-...","status":"PENDING","card":"agreed_vs_billed", ...}
```
Confirms the endpoint the FE's per-card thumbs button calls works end to end and
persists a correction row. The UI button itself renders (visible in `insight_bubble.png`)
but a successful click-and-network-round-trip was not independently captured in
Playwright — reported honestly as not done, not rounded up.

## Result

- Real Azure DI extraction + real Azure OpenAI narration ran (not mocked): **PASS**
- Intelligence bubble renders under the assistant answer with verdict + findings:
  **PASS**
- Discuss chip works (composer prefilled with the finding's context): **PASS**
- Per-card thumbs endpoint works (confirmed via direct API call): **PASS**
- Per-card thumbs UI click-through: **not independently confirmed in this run**

Run against local stack with real Azure AI services, ENABLE_ATTACHMENT_INSIGHTS
force-enabled by restarting BE+worker for the duration of this scenario only.
