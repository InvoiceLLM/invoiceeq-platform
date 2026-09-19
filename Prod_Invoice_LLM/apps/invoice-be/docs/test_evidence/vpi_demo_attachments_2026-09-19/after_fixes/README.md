# Chat-attachment regression vs newly-fixed backend (2026-09-19, after BE Gap 707/708/709/711)

Real stack: uvicorn 127.0.0.1:8000 (health 200 before, mid-run and after), Postgres
127.0.0.1:5433, queue worker draining a stale poison queue of pre-existing corrupted
PDFs (expected noise per task brief, not counted). Tenant
00000000-0000-0000-0000-000000000000. 17 cases: 11 new control scenarios (Set A,
../new_scenarios.md) + 6 re-asks of the originally-failed turns (Set B, from
../README.md / ../11_turns_transcript.txt). Harness: run_regression_after_fixes.py
(this dir), adapted from ../run_vpi_turns.py; polls extraction_status to the true
terminal set (EXTRACTED/EXTRACT_FAILED) per BE Gap 711, and bypasses the poll for
scenario A4 Turn A per the task's R4 instruction.

DB baseline confirmed against Postgres before and after -- see sql_evidence.txt. No
Invoice row was created for the credit note at any point; INBOUND/OUTBOUND/Bharat
aggregates are identical before and after (14/1,891,327.60, 12/5,248,631.00,
2/206,382.00). Backend stayed up the whole run.

## Set A -- 11 new control scenarios

| # | Question (short) | Expected | Actual | Verdict |
|---|---|---|---|---|
| A1 | Shree balance still unpaid, per this PO | INR 2,44,614.00 (SHR-2005+2006), SHR-2004 excluded (PAID) | INR 2,44,614.00, SHR-2005+SHR-2006 named, SHR-2004 excluded as paid | PASS |
| A2 | Any of this statement's 3 vendor payments still unpaid? | No -- INR 0.00, all 3 PAID | Dumps a whole-book reconcile: correctly shows OM-2000/BHA-2002/SHR-2004 as PAID/agrees, but never states the Yes/No or the 0.00 conclusion, buried under 20 unrelated OUTBOUND rows plus a spurious VPI-OUT-2018 difference line | FAIL |
| A3 | What is left on Bharat account after this advice? | INR 1,03,191.00 (BHA-2003 open) | Only reports BHA-2002 PAID/agrees; never mentions BHA-2003 or 1,03,191.00 | FAIL |
| A4 Turn A | Ask immediately, before extraction terminal | processing state, no question back | I'm still reading that document -- give me a moment and ask again. | PASS |
| A4 Turn B | Same question, after polling to EXTRACTED (fresh session) | 5/12/8 delivered = NAT-2006, INR 79,956.80 owed, NAT-2007 named as duplicate | Same still-reading message, despite extraction_status=EXTRACTED and candidates populated in the DB at ask-time | FAIL (regression, see defect 3 below) |
| A5 | Sales order from customer, or purchase we placed? | Purchase placed with Rajesh Steel | This is a purchase order we placed with Rajesh Steel Corporation, not a sales order from a customer. | PASS |
| A6 | No party column -- which lines owed vs owed to us? | 3 payable 2,66,739.00 / 3 receivable 11,97,985.00 / 6 unmatched 18,25,910.00 | Same whole-book reconcile dump as A2 -- no payable/receivable/unmatched classification at all | FAIL |
| A7 | What do we still owe Om Stationery Mart? | INR 70,446.00 (OM-2001+2002), OM-2000 excluded (PAID) | Only reports OM-2000 PAID/agrees; never mentions OM-2001/2002 or 70,446.00 | FAIL |
| A8 | Outstanding payable balance with Om (rephrased) | INR 70,446.00, identical to A7 | Identical wrong answer to A7 (same OM-2000-only reply) | FAIL (R6 consistency holds -- both wrong the same way -- but R1 content is wrong) |
| A9 | Rupee value of this delivery, per the challan itself | I cannot tell -- no rate/amount column on the challan | The delivery challan DC-RSC-0812 does not state a total or currency, so its rupee value cannot be determined from the challan itself. | PASS |
| A10 | Which invoice number does this credit note quote? | It does not quote one -- no number printed | The credit note does not explicitly state which invoice number it quotes; it was compared with BHA-2003 and BHA-2002, but the available data does not identify one as the quoted invoice. | PASS |
| A11 | Does the credit note change the 15-Sep run? | Yes; Bharat line 1,03,191 to 60,416 (BHA-2003, not BHA-2002/PAID); run total 7,83,885.80 to 7,41,110.80 | Yes... Applied to invoice BHA-2003: 103191... Net amount owed: 60416... BHA-2002 is marked PAID, so excluded. Correct figure and correct invoice choice; does not restate the whole-run total delta | PASS (core figure + invoice choice correct; the run-total figure is omitted, not wrong) |

Score: 6 PASS, 5 FAIL out of 11.

## Set B -- 6 re-asks of the originally-failed turns

| # | Question (short) | Original result | Actual now | Verdict |
|---|---|---|---|---|
| B2 | Is the Ganesh Bearings invoice within this PO? | MISS -- ambiguous card, no comparison | Full comparison: GBP-2011 matches exactly (68,676.00), GBP-2012 correctly rejected (103,368.00, wrong quantities/lines) | FIXED / PASS |
| B5 | Check delivery against invoice (DC-NMT-2291) | MISS -- ambiguous card, no comparison | Full comparison: 3 lines matched to NAT-2006 and NAT-2007, NAT-2007 correctly excluded as duplicate, 79,956.80 owed | FIXED / PASS |
| B6 | Any short delivery here? (DC-BHF-0455) | MISS -- extraction defect, items empty (Gap 710, deliberately not fixed) | items now has all 3 lines (25/15/4, matching the README exactly) -- see sql_evidence.txt. Comparison answer correct: no short delivery. | Reported separately, not tallied -- did NOT reproduce Gap 710 this run (see note below) |
| B9 | What do we still owe Shree Packaging? | MISS -- same defect as A3/A7 | Only reports SHR-2004 PAID/agrees (1 deduction shown separately rather than netted); never states SHR-2005+2006=2,44,614.00 | FAIL (unchanged) |
| B10 | Match this statement to our books | MISS -- reconcile bails on empty referenced_documents | Now runs the whole-book reconcile (the silent cap-at-10 from the original README is gone -- it now says and 10 further), but still the wrong branch for the question: no ledger classification, 20 irrelevant OUTBOUND rows again | still FAIL, different symptom |
| B11 | Bharat sent this - what do we actually owe them? | MISS -- wrong number, INR 1,63,607 (BHA-2002 wrongly summed) | INR 60,416.00 -- Invoice BHA-2002 excluded because its status is PAID and it is already settled. Correct figure, correct exclusion. | FIXED / PASS |

Set B score (excluding B6, reported separately per the task's instruction): 3 FIXED, 2 still FAIL, out of 5 tallied.
## Note on B6 (Gap 710)

The task brief states Gap 710 (dropped delivery-note line-item table) was deliberately
not fixed and B6 is expected to still fail. This run's own extraction -- queried
directly from chat_attachments.extracted_json, not from the chat answer -- shows all
3 lines present and correct. Either the extraction is non-deterministic (Doc
Intelligence / LLM re-run got lucky this time) or something else already fixed it as
a side effect; this was not investigated further, per scope (report, don't fix). See
sql_evidence.txt for the raw items dump. Flagging this discrepancy rather than
silently accepting the premise or silently marking it a pass.

## Defects found (grouped by root cause, not by symptom)

1. Amount owed for vendor X and what is left after this advice route into the
   generic reconcile branch instead of the vendor-ledger/amount-owed branch, when the
   attachment is a single-invoice-referencing document (remittance advice).
   A3, A7, A8, B9 all show the identical shape: the branch correctly resolves the ONE
   invoice the attached document itself references (and correctly reports its PAID
   status), then stops -- it never widens to what else is open for this vendor,
   which is the actual question asked. agents/query_agent.py's intent routing for
   these phrasings (_run_attachment_reconcile_branch, based on the 1 reference(s)
   ... 1 agree wording seen in the transcript) needs to fall through to (or invoke)
   the vendor-open-balance ledger -- the same one A1 used successfully, since A1's PO
   attachment DID reach the correct amount-owed path and correctly excluded a PAID
   invoice. The fix that shipped clearly reaches the compute_amount_owed()/
   is_settled() layer correctly (A1, A11, B2, B5, B11 all prove that layer works) --
   the defect is upstream, in which attachments/questions get routed there at all.

2. BANK_STATEMENT questions (A2, A6, B10) never reach a per-question answer; they
   always fall into one fixed whole-book reconcile template, regardless of whether
   the question asks is X unpaid (A2, needs a Yes/No plus figure), sort into
   payable/receivable/unmatched (A6, needs 3 buckets), or match this statement
   (B10, generic). Root cause 2 from the original README (party_name/limit-10
   truncation) appears partially addressed -- the truncation now announces and N
   further instead of silently capping -- but the underlying branch is still a
   single hardcoded template with no per-question shaping, so all three questions
   get the same answer shape regardless of what was actually asked.

3. New regression, not in the original 5 root causes: once an attachment has been
   asked-against while still non-terminal (the R4 still-reading path), later
   requests against the SAME attachment id keep getting the still-reading answer
   even after extraction_status reaches EXTRACTED in the database (A4 Turn B).
   Confirmed via direct DB read: chat_attachments.extraction_status = EXTRACTED
   and candidate_invoice_ids populated at the moment Turn B (a brand-new chat
   session) was asked, yet agents/query_agent.py line 5766's check
   (attachment.extraction_status != EXTRACTED) still fired. B5 -- a fresh
   upload of the identical source PDF that was never asked-against before terminal
   -- answered correctly in the same run, isolating the trigger to this exact
   attachment id was read early, consistent with a stale ORM-cached row rather
   than a fresh SELECT on the second ask.

## Files
- run_regression_after_fixes.py -- the probe script (17 cases, adapted from ../run_vpi_turns.py).
- 17_cases_transcript.txt -- console transcript of the run.
- 17_cases_raw_bubbles.json -- full raw response payloads per case.
- sql_evidence.txt -- before/after Postgres queries and the two direct chat_attachments reads (B6, A4).
