# VPI demo tenant — re-driven after the six real-data fixes (2026-09-18)

Same tenant, same 26 invoices, **not reseeded**: `00000000-0000-0000-0000-000000000000`, the rows
the parent directory's captures were taken from. This folder is the *after* so the two read
together.

Stack: `next dev` on :3000 → route handler → uvicorn on :8000 → real Postgres
(`127.0.0.1:5433/invoice_db`, BE Gap 697 — `127.0.0.1`, never `localhost`) → real Azure OpenAI for
the chat capture. Driven in a real Chromium via Playwright, `DISABLE_CLERK_AUTH=true`,
`ALLOW_MOCK_AUTH=true`. Nothing here is a fixture or a mock.

Covers: the three defects that had no gap number (double render, collapse predicate, area counts)
and **BE Gaps 704, 705, 706**. Written up in BE Feature 34 §18 and FE Feature 23 §16.

## What each capture shows

| File | Role | What it is evidence of |
|---|---|---|
| `admin.png` / `admin_text.txt` | Admin, all grants | **9 lines, each rendered exactly once**, counted on the rendered screen with the rank cut revealed. **No area rows at all** — one person works this tenant, so nothing collapses (D20: "a solo owner collapses nothing"). The cash line reads the whole open book |
| `admin_with_colleague.png` / `_text.txt` | Admin, all grants | The collapse path, with a real reason for it. **"Decisions — 2 pending. someone else is working this"** — not 5, and not "someone else" by accident |
| `auditor.png` / `auditor_text.txt` | `can_audit` only | 5 lines, each once. The full cash position (D44) |
| `trainer.png` / `trainer_text.txt` | `can_train` only | 4 correction lines, each once. No cash line |
| `atlas_lines_admin_after.json` | Admin | The raw `GET /atlas/lines` payload behind `admin.png` |
| `sage_attention_answer_after.json` | — | The live chat answer to "Which invoices need my attention?" (BE Gap 706), with its generated SQL |

## The numbers, and what they are checked against

**The cash line** (BE Gap 705) reads:

> Over the next 30 days you are committed to ₹16,24,588.60 across 11 invoice(s), and expecting
> ₹42,50,646.00 across 10.

Checked against a **direct SQL sum run separately from the code path**, over the same statuses and
the same 30-day window on this tenant: 11 / 1624588.6 and 10 / 4250646.0. Identical.

Before the fix the same line read *"committed to ₹5,17,146.80 across 2 invoice(s), and expecting
₹0.00 across 0"* — payables restricted to invoices awaiting a decision, receivables to invoices
taken through a manual confirm-send.

**"Which invoices need my attention?"** (BE Gap 706) answers **three** — `NAT-2007`, `RAJ-2009`,
`VPI-OUT-2014` — matching `showcase/vpi_demo/README.md`'s ground truth. It answered two before; the
generated SQL filtered `LIKE '%duplicate%'`, which structurally excludes the tax-mismatch invoice.

**No `why` field contains `{'` or `':`** on any line, on any role (BE Gap 704). The duplicate
doubt now reads *"Possible duplicate: Rajesh Steel Corporation invoice RAJ-2008 has the same date
and total (437,190.00) but a different number (RAJ-2009). Check whether this is a re-issue."* and
the references are `#RAJ-2009, 2008, 437,190.00, 2009` — four real identifiers where there were
twenty-two digit fragments of a UUID.

## How the roles and the colleague were simulated, stated plainly

Both are artefacts of the local mock-auth setup, not of the product, and both are reversed:

- **Roles.** Under `ALLOW_MOCK_AUTH` a browser with no `Authorization` header always authenticates
  as one shared identity (`user_test_default`). The parent README records the technique this
  directory reuses: flip that row's grant flags in Postgres between captures, and send
  `Bearer test_restricted_…` so the token resolves to NO_ROLE and the grants come from the row.
  **The row was restored to Admin / all grants at the end** and verified.
- **The colleague.** `admin_with_colleague.png` needed another user to be *working* the decisions
  area, which the new predicate reads from `atlas_action_log`. One row was inserted for
  `user_test_vpi_auditor` on `audit-approve-530bd65a-…` and **deleted immediately after the
  capture** (`atlas_action_log` for this tenant is back to 0 rows). Without it the tenant is solo
  and correctly collapses nothing — which is what `admin.png` shows.

## Known noise in the captures

`auditor.png` and `trainer.png` record three console errors: Clerk's CDN script fails a CORS
preflight. That is caused by the capture technique — sending an `Authorization` header on the
document request — and not by any change in this pass. `admin.png`, captured without that header,
has **zero page errors**.
