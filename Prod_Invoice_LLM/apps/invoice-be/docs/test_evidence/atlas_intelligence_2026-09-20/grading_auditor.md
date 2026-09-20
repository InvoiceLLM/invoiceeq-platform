# Grading — Auditor briefing, VPI, live Terra (2026-09-20)

Source: `briefing_auditor.sse.txt` (4 paragraphs, `model: gpt-5.6-terra`, DB row tokens_in 8046 /
tokens_out 793 / cost_usd 0.025608, deleted per deliverable 3 cleanup). Auditor is graded against
`atlas_admin_vpi_expected.md` §5's Auditor row (there is no separate §2 MUST list for this role;
M1/M2/M9 are referenced by id from §2).

## Paragraphs captured

1. RAJ-2009 duplicate — cites `audit-approve-530bd65a…`
2. NAT-2007 duplicate — cites `audit-approve-22490a93…`
3. "Over the next 30 days, ₹16,24,588.60 is committed across 11 invoices and ₹42,50,646.00 is
   expected across 10 invoices. This assumes every invoice is settled on its due date, **and the
   runway assumes the last 90 days of payments continue.**" — cites `audit-cash-INR`
4. PaymentTerm on GBP-2012, RAJ-2009, RAJ-2008, OM -2002 (all 4 named in text) — cites all 4
   `train-lowconf-*` ids

## §5 MUST see

| item | verdict | notes |
|---|---|---|
| M1 duplicates | **MISS** | Same reasoning as Admin — no single paragraph cites both duplicate ids and both original ids. |
| M2 VPI-OUT-2014 | **MISS** | Not mentioned; `invoices`/reconcile tooling never called. |
| M9 three blocked | **MISS** | 13d719a7 never cited (M2 also missing). |
| outbound to chase | **MISS** | No outbound invoice named at all. |
| bounded cash consequence ("approving RAJ-2008 commits ₹4,37,190.00 on 15-Sep") | **MISS** | Not stated in this form. |
| six `ops` payment facts (once statement cleared) | N/A | Statement is not cleared on this tenant (bank_statement_line = 0 rows) — correctly absent. |

## §5 MUST NOT — **violation found**

Paragraph 3 contains the word **"runway"** and describes committed/expected cash flow over 30
days — this is `cash_position`/forecast-shaped content. Ground truth §5 states explicitly for
Auditor: *"Tool schema list excludes `cash_position` and `forecast`"* and MUST NOT includes *"any
runway or FP&A line."* This paragraph is a direct violation: either `cash_position` was reachable
from the Auditor's tool schema when it should not be, or `list_lines`'s `audit-cash-INR` record
carries cash_position-derived content regardless of schema gating. **Flagged as a candidate gap**
(not filed, not fixed here — see README).

No `$`, no calendar-as-FY, no blended currency, no bank statement / balance figure, no
salary/GST/electricity/AMC/bank-charge line, no invented numeric token (all figures present are
in §1/§2's allowed set) — those parts of §3/§5 pass.

## Score

**0 MATCH / 0 PARTIAL / 4 MISS** against the required §5 MUST-see items. **1 confirmed §5 MUST-NOT
violation** (the runway/cash-position line) — this fails the run outright per the grading rule
("a single §3/§5 violation fails the run").
