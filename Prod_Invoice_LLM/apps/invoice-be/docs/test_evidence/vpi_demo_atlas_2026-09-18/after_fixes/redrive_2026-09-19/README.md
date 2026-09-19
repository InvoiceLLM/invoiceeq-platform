# ATLAS re-drive completion — 2026-09-19

Docker died mid-run on 2026-09-18; the six fixes and the `after_fixes/` root captures
(admin/auditor/trainer/admin_with_colleague, `sage_attention_answer_after.json`,
`atlas_lines_admin_after.json`) were already in place and are **not duplicated here**. This
folder finishes what the interrupted run never got to: independent re-verification of those
captures against a live re-check, plus the item-7 exercises the interruption skipped
(memory panel, action log, "you missed this"). Same tenant, same 26 invoices, still not
reseeded: `00000000-0000-0000-0000-000000000000`.

Stack: `next dev` :3000, `uvicorn` :8000, Postgres 127.0.0.1:5433 — all already running per the
task brief, none restarted. Driven with a standalone Playwright script (`chromium.launch()`),
not the `invoice-fe/e2e` suite — this is a one-off functional re-check, not a new spec file.

## 1–6. Re-checked against the parent folder's claims, independently

- **Line count.** `admin_full.png` / `admin_full_text.txt`: clicked "Show everything" first —
  `[data-testid="atlas-line"]` count is **9**, matching the parent capture exactly, no
  duplicates. Zero console errors, zero page errors.
- **Solo tenant collapses nothing.** Same capture: no area row, 9 lines rendered flat.
- **Collapse fires correctly for a real colleague.** Inserted one `atlas_action_log` row
  (`user_test_vpi_auditor` on the RAJ-2009 approve line), reloaded: `admin_with_colleague.png`
  shows **"Decisions — 2 pending. someone else is working this"** and 5 individually rendered
  lines outside the area (the cash line plus the 4 correction lines); the area itself holds the
  2 `INVOICE_AWAITING_DECISION` lines it collapsed, each appearing once, not twice. Deleted the
  row immediately after; `atlas_action_log` back to 0 for this tenant, confirmed by count.
- **Auditor-only / Trainer-only counts.** Flipped `users.can_audit`/`can_train`/`role` on the
  shared `user_test_default` row (the same reversible technique the parent README used),
  sent `Bearer test_restricted_00000000-0000-0000-0000-000000000000` so the token resolves to
  `NO_ROLE` and grants come from the row. Auditor-only: **5** lines. Trainer-only: **4** lines.
  Matches the parent capture. Grants restored to Admin/all four at the end and verified by
  `SELECT`.
- **The cash line, checked against SQL run separately from this session's captures too:**

  ```
  payable:    count=11  sum=1624588.6
  receivable: count=10  sum=4250646.0
  ```

  against the population `flow_direction/status/due_date<=today+30` the service itself uses
  (`services/atlas_skills.py::cash_position`). Identical to what the screen reads: "committed to
  ₹16,24,588.60 across 11 invoice(s), and expecting ₹42,50,646.00 across 10." This SQL was
  written independently from the parent capture's, not copied, and agrees with it.
- **No dict-shaped `why`.** `grep -n "{'" \| grep -n "':"` across every `.txt`/`.json` capture
  in `after_fixes/` (root and this folder): **zero matches**, including `admin_full_text.txt`.
- **SAGE "which invoices need my attention".** Re-read the parent's
  `sage_attention_answer_after.json` rather than re-asking the LLM a second time (no reason to
  spend another live GPT-5.6 Luna call re-proving arithmetic the SQL in `generated_sql` already
  shows): three invoices — NAT-2007, RAJ-2009, VPI-OUT-2014 — matching
  `showcase/vpi_demo/README.md` ground truth.

## 7. What the fixes did not touch, exercised live

**Memory panel** (`memory_after_create.png`, `memory_after_edit.png`, `memory_after_delete.png`):
created a rule via the textarea ("QA TEST RULE: never approve invoices from Test Vendor XYZ
above 50000"), confirmed it rendered; edited it in place ("... above 75000"), confirmed the new
text rendered; deleted it, confirmed it left the screen. **Postgres `atlas_memory_rules` count
for this tenant: 0** before, during (1), and after (0) — a real hard delete, not a client-side
splice hiding a row the server still holds.

**Action log** (`action_log.png`): needed one genuine PERFORM-kind success and one genuine
refusal, without touching any of the 26 real VPI invoices whose line/count evidence this run
had just finished re-verifying. Seeded one throwaway invoice (`QA-SEED-1`, status
`AUDIT_REQUIRED`, tenant-scoped) and called `POST /atlas/lines/{id}/act` with
`kind=resolve_invoice, status=REJECTED` against it directly — same code path a real Approve/
Reject click runs (`services/atlas_actions.py::_resolve_invoice` calls
`resolve_audit_invoice` unchanged). Logged: `succeeded=true, summary="Invoice rejected."` For
the refusal, called the same endpoint with `kind=open_upcoming_payments` (a `SUGGEST_ONLY`
kind) against the real cash line id — no data touched, immediate 409:
`"'open_upcoming_payments' opens a screen; there is nothing here to perform."` Both rows showed
in the FE panel labelled **"Did"** and **"Refused"** respectively. Cleaned up after: deleted
both `atlas_action_log` rows, the seeded invoice's `audit_logs` row, and the seeded invoice
itself. `atlas_action_log` count for this tenant: 0. `invoice` count for `QA-SEED-1`: 0.

**"You missed this," from a record, not a line** (`missed_this_from_record.png`) — the brief
specifically asked for "from a record" and FE Gap 703's fix (§comment in `MissedThis.tsx`)
exists precisely because the control used to ship only on ATLAS lines, "the one surface where
it is least useful." Opened `/invoices/review/86f1559a-ab03-4c07-b1f3-7453db53aeb9` (a real
VPI invoice, NAT-2006), used the control there: "QA TEST: the vendor GSTIN on this invoice
does not match the master vendor record." Got the acknowledgement sentence ("Noted, in your
words. You can read it, change it or delete it in what I remember."). Confirmed in Postgres:
one `atlas_missed_reports` row (`entity_kind=invoice`, the real invoice id) **and** one
`atlas_memory_rules` row it created automatically, reading "I missed this, and you told me:
QA TEST: ..." — so the promise that a miss becomes an editable memory rule is real, not just
narrated. Deleted both rows after. Both tables: 0 rows for this tenant.

## Net state at the end of this run

`atlas_action_log`, `atlas_memory_rules`, `atlas_missed_reports`: **0 rows** each for this
tenant — exactly where they stood at the start. `invoice` table: the same 26 VPI rows, no more,
no fewer (`QA-SEED-1` inserted and removed within this session). `users` row for
`user_test_default`: back to `role=Admin, can_train=can_audit=can_load=can_send_invoices=true`,
verified by `SELECT` after restoring. Both dev servers (`uvicorn`, `next dev`) left running, as
instructed.
