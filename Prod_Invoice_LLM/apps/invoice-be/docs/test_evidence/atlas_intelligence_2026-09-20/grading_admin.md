# Grading — Admin briefing, VPI, live Terra (2026-09-20)

Source: `briefing_admin.sse.txt` (4 paragraphs, 0 questions, `model: gpt-5.6-terra`, DB row
tokens_in 8046 / tokens_out 975 / cost_usd 0.027792, deleted per deliverable 3 cleanup).
Grading method per `atlas_admin_vpi_expected.md` §6, applied by hand (deterministic set/figure
comparison, not an LLM judge). Note on citation matching: ground truth's "Must cite" ids are
bare record ids (e.g. `530bd65a-…`, `cash-INR`); the live system's `record_id` values are
role/area-prefixed (`audit-approve-530bd65a-…`, `audit-cash-INR`). Matched by **substring
containment** of the bare id inside the emitted `record_id` — the only interpretation under
which any citation test can ever pass against this build's actual naming convention.

## Paragraphs captured

1. RAJ-2009/RAJ-2008 duplicate — cites `audit-approve-530bd65a…`, `train-lowconf-530bd65a…`
2. NAT-2007/NAT-2006 duplicate — cites `audit-approve-22490a93…`
3. Cash: "₹16,24,588.60 committed across 11 invoices, ₹42,50,646.00 expected across 10" — cites `audit-cash-INR`
4. PaymentTerm review on GBP-2012, RAJ-2008, OM -2002 (3 of 4 due fields) — cites `train-lowconf-33d6ccd5…`, `train-lowconf-d5869da2…`, `train-lowconf-ff4a9fe0…`

No `question` event fired.

## M1–M12

| item | verdict | notes |
|---|---|---|
| M1 duplicates | **MISS** | Must-cite = {530bd65a, 22490a93, d5869da2, 86f1559a} all four in one paragraph. P1 has only 530bd65a, P2 only 22490a93 — no single paragraph is a superset. Combined exposure figure ₹5,17,146.80 never stated. |
| M2 VPI-OUT-2014 | **MISS** | Not mentioned anywhere; `invoices` tool never called this run. |
| M3 Deccan advance | **MISS** (expected — NO TOOL TODAY) | Not mentioned. |
| M4 GST/IGST head | **MISS** (expected — NO TOOL TODAY) | Not mentioned. |
| M5 15-Sep shortfall | **MISS** | `forecast` never called; no shortfall/balance/`None` language at all. |
| M6 payables inflated | **PARTIAL** | Citation test passes (`audit-cash-INR` ⊇ `cash-INR`); as-extracted figure ₹16,24,588.60 present verbatim. Clean figure ₹11,07,441.80 and the ₹5,17,146.80 difference are absent — some listed figures missing. |
| M7 receivables concentration | **PARTIAL** | Total ₹42,50,646.00 present verbatim, citation passes via `audit-cash-INR`. Deccan/Sunrise/Kaveri split figures and ids absent (expected — no split tool exists). |
| M8 nothing overdue / 17-Sep total | **MISS** | Not mentioned. |
| M9 three blocked invoices | **MISS** | 13d719a7 (VPI-OUT-2014) never cited — no paragraph has all three ids. |
| M10 4 low-confidence PaymentTerm | **MISS** | P4 cites only 3 of 4 ids (missing 530bd65a/RAJ-2009 in that paragraph — it's cited only in P1, for a different purpose). No confidence decimals (0.485/0.414/0.406/0.332) appear anywhere. |
| M11 witnesses missing | **MISS** (expected — NO TOOL TODAY) | Not mentioned. |
| M12 no conventions | **MISS** | `memory_rules` never called; not mentioned. |

**Score: 0 MATCH / 2 PARTIAL / 10 MISS** (of which 3 MISS are the expected NO-TOOL-TODAY items: M3, M4, M11).

## INVENTED check

Numeric tokens across all 4 paragraphs: `437,190.00`, `4,37,190.00`, `79,956.80` — all in §1/§2 allowed
set. `16,24,588.60`, `42,50,646.00` — both in §2 (M6, M7). **0 invented tokens.**

## §3 MUST NOT

| # | check | result |
|---|---|---|
| 1 | invented figure | pass — 0 found above |
| 2 | FP&A/margin language | pass — none |
| 3 | per-person speed/throughput | pass — none |
| 4 | `$` or blended currency | pass — none found (`grep '\$[0-9]'` empty across all captures) |
| 5 | calendar 2026 as fiscal year | pass — no FY language at all |
| 6 | `0` where answer is `None` | pass — forecast/balance never invoked, so nothing to blank incorrectly |
| 7 | a 4th "needs attention" invoice | pass — GST head / Deccan concentration never raised |
| 8 | inbound line-math alert | pass — none |
| 9 | attachment/write promise | pass — none |

**0 §3 violations.**

## §4 question

**Did not fire.** No `question` event anywhere in the run. Ground truth requires exactly one
question (RAJ-2009 vs RAJ-2008) in every Admin run. This is a functional gap — see README
candidate-gap list.
