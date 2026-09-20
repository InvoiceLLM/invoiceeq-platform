# Admin re-run — graded against `atlas_admin_vpi_expected.md` §2 (corrected ids) and §6

Capture: `briefing_admin.txt`. Model `gpt-5.6-terra`, 4 paragraphs + 1 question, 0 dropped,
no truncation. Rule applied: **a MUST item is MATCH if ANY of its listed ids is cited and every
listed figure appears in that paragraph; PARTIAL if the citation passes and a figure is absent;
MISS if no paragraph cites any listed id.** Ids compared whole, no substring matching.

The four paragraphs, by the id they cite:

| # | cites | subject |
|---|---|---|
| P1 | `audit-approve-530bd65a-…`, `train-lowconf-530bd65a-…` | RAJ-2009 duplicate + its unread PaymentTerm |
| P2 | `13d719a7-c53f-4204-95fc-79f5b73959ba` | VPI-OUT-2014 tax mismatch |
| P3 | `audit-approve-22490a93-…` | NAT-2007 duplicate |
| P4 | `cash-INR` | payable/receivable over 30 days |
| Q | `530bd65a-…` | the duplicate question (deterministic, BE Gap 718) |

| item | verdict | why |
|---|---|---|
| M1 duplicates | **PARTIAL** | P1 and P3 each cite a listed id and state that invoice's figure verbatim (437,190.00 / 79,956.80). The listed **₹5,17,146.80** exposure appears nowhere — it is the sum of the two, which no tool renders and ATLAS may not compute (§1). |
| M2 VPI-OUT-2014 | **PARTIAL** | P2 cites `13d719a7-…`, the only id this outbound invoice has, and reproduces the alert's own working (409500.00 + 73710.00 vs 483850.00). The listed **+₹640.00** difference is absent for the same reason. |
| M3 Deccan advance | **MISS** | NO TOOL TODAY, expected. No paragraph cites `ec8acc1d-…`. |
| M4 GST head | **MISS** | NO TOOL TODAY, expected. |
| M5 15-Sep shortfall | **MISS** | `forecast` returned **0 rows** (`tool_calls` confirms the dispatch), because `bank_statement_line` is empty so there is no balance to go short against. No paragraph cites any of the five payable rows. Correct absence, not a silent zero — §3 item 6. |
| M6 payables inflated | **PARTIAL** | P4 cites `cash-INR` and states **₹16,24,588.60** across 11 verbatim. The clean ₹11,07,441.80 and the ₹5,17,146.80 difference are derived figures no tool renders. |
| M7 receivables | **PARTIAL** | P4 cites `cash-INR` and states **₹42,50,646.00** across 10. The per-customer split has no tool (§2 records it as NO TOOL TODAY for the split) and is absent. |
| M8 nothing is overdue | **PARTIAL** | P2 cites `13d719a7-…`, one of the seven 17-Sep outbound rows this item lists, so the citation test passes; none of M8's own figures (0 overdue, 9/10 open, ₹34,49,780.00) appear, and the briefing makes no overdue claim at all. Recorded as PARTIAL by the literal rule; in content it is closer to a MISS, and it is **not** a §3 item 1 violation — nothing false was said. |
| M9 three blocked | **PARTIAL** | All three blocked invoices are named across P1/P2/P3, each citing a listed id, and **no fourth invoice is presented as needing attention** (§3 item 7 clean). The item's own figures (3, ₹10,00,996.80) are absent — again a sum. |
| M10 PaymentTerm | **PARTIAL** | P1 cites `train-lowconf-530bd65a-…` and says the PaymentTerm was not read confidently. The four confidence scores (0.485 / 0.414 / 0.406 / 0.332) are not stated, and the other three invoices are not named on this run. |
| M11 missing witnesses | **MISS** | NO TOOL TODAY, expected. |
| M12 no conventions | **MISS** | No paragraph about the empty rule set; `memory_rules` was not called. |

**Score: 0 MATCH / 7 PARTIAL / 5 MISS** (M3, M4, M11 expected MISS; M5 MISS is the empty
`forecast`; M12 is a real omission).

**INVENTED tokens: 0.** Every money-shaped token in the four paragraphs — 437,190.00,
4,37,190.00, 79,956.80, 16,24,588.60, 42,50,646.00, 409500.00, 73710.00, 483850.00 — came out of
a tool row this run; `dropped_paragraphs` is 0, so no paragraph was removed for stating one, and
`assert_briefing_no_undeclared_numbers` would have dropped any that had been.

**§3 MUST-NOT: 0 violations.** No `$`; no FP&A or margin language; nothing about any person's
speed; no fiscal-year claim; no `0` where the answer is unknown (the balance, `projected` and
`runway_days` are `None` today and the briefing states none of them); exactly three invoices
presented as needing attention; no inbound line-math alert; no promise to attach or fetch.

**The question (§4).** *"Rajesh Steel Corporation RAJ-2009 looks like a copy of RAJ-2008. Is it
a genuine second order?"* — `answer_kind: free_text`, cites `530bd65a-…`. §4's ground-truth
wording also names the date and the ₹4,37,190.00 and cites `d5869da2-…` as well; this question
is built deterministically from the alert sentence and cites the one row it was built from. It
satisfies §4's required properties except the second citation: **exactly one question, the
right pair, free_text, and the highest-rupee thing ATLAS genuinely cannot decide.** Before this
change no question fired at all, on six consecutive live runs.
