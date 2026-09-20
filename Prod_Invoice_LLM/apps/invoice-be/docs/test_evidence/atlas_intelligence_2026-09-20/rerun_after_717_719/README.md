# ATLAS Intelligence — VPI re-run after BE Gaps 717/718/719 and FE Gap 706 — 2026-09-20

Founder approval: "lets fix all five" (2026-09-20). Real local Postgres
(`127.0.0.1:5433/invoice_db`, BE Gap 697 — never `localhost`), real Azure OpenAI
`gpt-5.6-terra` (`AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME=gpt-5.6-terra`, confirmed on every
`done.model` below), tenant `00000000-0000-0000-0000-000000000000` (VPI), `as_of`
**2026-09-15** — the anchor `docs/atlas_admin_vpi_expected.md` grades against.

## How this was run, and why not through the browser

`agents/atlas_agent.run_briefing()` was called directly, once per role, with an **explicit
`GrantSet`**:

| role | GrantSet |
|---|---|
| Admin | `can_audit=True, can_train=True, can_load=True, is_admin=True` |
| Auditor | `can_audit=True` (and nothing else) |
| Trainer | `can_train=True` (and nothing else) |

**The mock-auth shared user cannot express a role.** Under `ALLOW_MOCK_AUTH`,
`dependencies.py`'s test-token branch resolves every `test_` bearer — and the browser's
header-less request — to one identity, `user_test_default`, bound to one `users` row; the token
carries no role and no user id into `user_id`. The 2026-09-20 evidence captured the three roles
by **editing that row's `role`/`can_audit`/`can_train` columns in Postgres between captures**
and restoring them afterwards. Driving `run_briefing()` with the grants stated in the call is
the same three briefings with none of that mutation: no `users` row was touched on this run, no
`atlas_briefings` row was written (this path is the agent, not the cached route), and no
dismissal, memory rule or invoice was created or deleted. The tenant is exactly as it was found.

Raw captures: `briefing_admin.txt`, `briefing_auditor.txt`, `briefing_trainer.txt` — every
event verbatim, then the run's model, tokens, cost, drop count and `tool_calls`.

## Three score lines (graded with the corrected `atlas_admin_vpi_expected.md` §0/§6)

- **Admin: 0 MATCH / 7 PARTIAL / 5 MISS** of 12 (3 of the 5 MISS are the NO-TOOL-TODAY items
  M3/M4/M11; M5 needs a `forecast` row this tenant cannot produce). 0 INVENTED tokens.
  0 section-3 violations. **The interview question fired** — deterministically (BE Gap 718).
- **Auditor: 0 MATCH / 3 PARTIAL / 1 MISS** of the 4 required section-5 items. 0 INVENTED
  tokens. **1 section-5 MUST-NOT violation, unchanged and pre-existing** — the `audit-cash-INR`
  runway sentence (see below). Question fired.
- **Trainer: 0 MATCH / 1 PARTIAL / 2 MISS** of the 3 required section-5 items. 0 INVENTED
  tokens. **1 section-5 MUST-NOT violation, unchanged and pre-existing** — duplicate content on
  the Trainer's own low-confidence line. Question fired.

Per-item reasoning: `grading_admin.md`, `grading_auditor.md`, `grading_trainer.md`.

**Why there is still no MATCH.** §6's MATCH requires *every* listed figure of an item in one
paragraph. Several items list derived totals no tool renders (M1's ₹5,17,146.80 exposure, M2's
+₹640.00, M6's clean ₹11,07,441.80) — and ATLAS may not state a number a tool did not render
(§1, the guard `assert_briefing_no_undeclared_numbers`). Those items are **PARTIAL by
construction on today's build**, not by failure: the citation is right, the stated figures are
right, and the missing ones are arithmetic ATLAS is forbidden to do. That is worth recording
rather than closing — the fix, when it is wanted, is a tool that renders the total, not a
prompt that permits the addition.

## What the two new guarantees did on this run

| gap | observed |
|---|---|
| **717** — every open-alert invoice is reported | Admin: the model covered all three itself (RAJ-2009, NAT-2007, VPI-OUT-2014), so **nothing was appended** — the guarantee was satisfied without firing. Auditor: the model wrote three paragraphs and left VPI-OUT-2014 out; the **fourth paragraph is the appended one** ("Vishwa Precision Industries Pvt Ltd VPI-OUT-2014 is still waiting on a decision. Subtotal (409500.00) + Tax (73710.00) does not match Grand Total (483850.00)"), cited to `13d719a7-…`. Trainer: the one open-alert row they can see (RAJ-2009's trainer line) was cited by the model's own first paragraph, so nothing was appended. |
| **718** — the duplicate pair is asked about | **Fired on all three roles**, which is the whole point: it fired on zero of the six live runs captured on 2026-09-20. Text: *"Rajesh Steel Corporation RAJ-2009 looks like a copy of RAJ-2008. Is it a genuine second order?"*, `answer_kind: free_text`, cited to `530bd65a-…` (Admin/Auditor, the `invoices` row) and to `train-lowconf-530bd65a-…` (Trainer, the only row they hold). Both numbers are read out of the pipeline's own alert sentence. |
| **719** — a grant change dates the briefing | Not exercised here (no grant was changed on this tenant). Asserted through the real Admin endpoints in `tests/test_atlas_briefing_router.py`. |

`dropped_paragraphs` is **0** on all three runs: nothing the model wrote and nothing the
deterministic paths appended failed a guard.

## Cost

| role | tokens in | tokens out | cost USD |
|---|---|---|---|
| Admin | 8,272 | 986 | $0.028376 |
| Auditor | 6,983 | 447 | $0.019330 |
| Trainer | 2,349 | 409 | $0.009606 |

## Two defects reproduced here, both PRE-EXISTING and NOT in this change's scope

Neither is caused by 717/718/719, and neither was filed or fixed — founder gate, CONVENTIONS
hard rule 1. Both were already recorded in the 2026-09-20 README's "candidate gaps".

1. **The Auditor gets a runway sentence.** `atlas_admin_vpi_expected.md` §5 says the Auditor's
   schema excludes `cash_position` and `forecast` — and it does; the tool was refused on this
   run (`no such tool is available to you`). The sentence arrives anyway because
   `services/atlas_skills.py::_cash_lines()` emits `audit-cash-INR` as an `AtlasCapability.AUDIT`
   **line**, which `list_lines` returns to any `can_audit` caller. The gate is on the tool, not
   on the line.
2. **The Trainer reads duplicate content.** It comes from their own low-confidence line's
   `alerts` field (BE Gap 716 put the invoice's `sa_alerts` on every line about an invoice), not
   from an audit-scoped tool — `invoices`, `cash_position` and `forecast` were all refused on
   the Trainer run. Whether a Trainer should see the invoice's alert at all is a design question
   about Gap 716's row content, not a leak through a capability check.
