# VPI demo -- 11 chat-attachment turns vs README section 5 ground truth (2026-09-19)

Real local stack: uvicorn on 127.0.0.1:8000, Postgres 127.0.0.1:5433 (invoice_db),
real Azure OpenAI (gpt-5.6-luna), real Doc Intelligence. VPI tenant
00000000-0000-0000-0000-000000000000, existing 26-invoice dataset (unchanged --
verified before/after, see below). No invoices uploaded in this session; only
chat-attachment turns per showcase/vpi_demo/README.md section 5.

**Environment finding before any turn ran:** the queue worker
(queue_worker/main_worker.py) that drains both the Azurite extraction-tasks-queue
and the Redis chat_tasks_queue was NOT running -- only two uvicorn processes
existed. Every chat attachment sat at extraction_status=PENDING, doc_type=OTHER
indefinitely (confirmed: 9 attachments stuck for 4+ minutes each). Started the
worker (python -m queue_worker.main_worker) mid-session; it drained the backlog
immediately. The first probe run (made while the worker was down) was discarded
in full; 11_turns_raw_bubbles.json and 11_turns_transcript.txt are the CLEAN
re-run, made after the worker was confirmed live and warm. The worker process was
left running at the end of the session (in addition to the two uvicorn processes
already up), since the stack cannot do attachment extraction without it.

Script: run_vpi_turns.py (this directory) -- one fresh chat session per turn,
attach + poll extraction_status to terminal, ask the README's exact question,
detect the "confirm which one" card and auto-confirm+re-ask once (mirroring how
scripts/attach_chat_eval.py already does this for the other attachment probe).

## Turn-by-turn grading

| # | Doc | Question | Result | Notes |
|---|---|---|---|---|
| 1 | PO-VPI-1041 (RAJ) | Does this PO match the Rajesh Steel invoice? | PARTIAL | Line/qty/rate matching correct and RAJ-2009 correctly flagged AUDIT_REQUIRED, but closing line sums RAJ-2008 + RAJ-2009 (874,380) as "amount owed" -- double-counts a duplicate invoice the answer itself just flagged. |
| 2 | PO-VPI-1042 (GBP) | Is the Ganesh Bearings invoice within this PO? | MISS | Got only "Would you like me to read the document, or compare it to your invoices?" -- no comparison happened. Match candidates (GBP-2011, GBP-2012) were not yet populated at ask-time; they existed in the DB minutes later. README's "new vendor -> confirm first link" flow never appeared. |
| 3 | PO-VPI-1043 (SHR) | Compare with Shree Packaging's August invoice | PARTIAL | Correctly named all three invoices (SHR-2004 PAID/matches, SHR-2005 matches, SHR-2006 variance vs PO, extra components correctly called out), but same double-counting bug as turn 1: sums SHR-2004 (PAID) + 2005 + 2006 = 366,508 and calls it "amount owed." |
| 4 | DC-RSC-0812 (RAJ) | Was everything on this challan invoiced? | MATCH | 6 coils + 30 bars correctly matched to both RAJ-2008 and RAJ-2009; correctly notes no prices on the challan so value comparison is incomplete; correctly flags RAJ-2009 duplicate. |
| 5 | DC-NMT-2291 (NAT) | Check delivery against invoice | MISS (the sharpest turn) | Got only the same ambiguous "Would you like me to read... or compare..." card -- no NOT_CHECKED PO-leg answer, no comparison at all. DB shows extraction was perfect (5/12/8 line items, PO-VPI-1039 captured, match_summary="probable match: NAT-2006", tier 2) -- the failure is not extraction, it is the chat layer returning the ambiguous card before match candidates are attached, and no compare intent was ever produced. |
| 6 | DC-BHF-0455 (BHA) | Any short delivery here? | MISS | Answer: "the delivery note contains 0 stated line items." Verified against the raw PDF text (pypdf dump) -- it has 3 clear tabulated lines (Hex Bolts 25, SS Washers 15, Torque Wrench 4), matching README exactly. extracted_json.items == [] in Postgres. Real extraction defect, not a matching defect: po_number ("PO-VPI-1040") extracted correctly from the same document, only the line table was dropped. |
| 7 | PA-VPI-0071 (OM) | Which invoice does this payment settle? | PARTIAL, load-bearing part missing | Correctly: "OM -2000: on file at 41,654.00 (status PAID) -- agrees with the document." But then lists 10 unrelated OUTBOUND receivables (VPI-OUT-2013..2023, to Kaveri/Sunrise/Deccan) as "open invoice(s) of yours NOT listed on their document" -- and never mentions OM-2001, the one payable the question actually needed. Root cause below. |
| 8 | PA-VPI-0072 (BHA) | Is Bharat Hardware fully paid? | PARTIAL, same defect | Correctly matches BHA-2002 PAID/103,191, but never states BHA-2003 is open at 103,191 (the actual answer to the question); same 10 irrelevant OUTBOUND invoices listed instead. |
| 9 | PA-VPI-0073 (SHR) | What do we still owe Shree Packaging? | MISS, same defect | Correctly matches SHR-2004 PAID; never states SHR-2005 (121,894) + SHR-2006 (122,720) = 244,614 open -- the entire point of the question. Same 10 irrelevant OUTBOUND invoices. |
| 10 | BankStatement_HDFC_4471_Aug2026 | Match this statement to our books | MISS | "I could not read a list of invoice references off that document, so there is nothing for me to reconcile against your records." Verified in Postgres that OCR extraction was in fact excellent -- items[] contains all 9 narration lines verbatim, including "NEFT DR OM STATIONERY MART INV OM -2000 UTR HDFCN26080512345", the 200,000 Deccan credit, GST/electricity/salary/AMC/charges, total 355,336.00 -- but referenced_documents and statement_lines are both []. The reconcile branch (_run_attachment_reconcile_branch) only reads referenced_documents; nothing maps the narration items into it for BANK_STATEMENT, so a genuinely well-OCR'd document produces a flat abstention. Not a "good abstain": the data needed to answer is sitting in the same row. |
| 11 | Credit note BHF-CN-2010 | Bharat sent this - what do we actually owe them? | MISS, wrong number | Got "computed net amount owed to Bharat is INR 163,607", built from terms CN -42,775 + BHA-2003 +103,191 + BHA-2002 +103,191. Expected: resolve to BHA-2003 only, net 60,416. The system DID correctly surface both BHA-2002 and BHA-2003 as candidates (the right ambiguity to raise), and confirming both is exactly what scripts/attach_chat_eval.py's own confirm-card protocol does -- but once both are confirmed, _amount_owed_block/compute_amount_owed() sums every confirmed invoice as a positive term with no exclusion for status == PAID and no "pick the open one" rule. The answer even says "Note: BHA-2002 is marked PAID, but it is included in the computed net" -- naming its own error without correcting it. DB verified clean on the parts that matter: no Invoice row was created for the credit note, and INBOUND/OUTBOUND aggregates are unchanged (14/1,891,327.60 and 12/5,248,631.00, Bharat spend still 206,382) -- Feature 26 D2/D3's "no aggregate moves" rule holds even though the chat answer's own arithmetic is wrong. |

Score: 1 clean MATCH (turn 4), 4 PARTIAL, 6 MISS, out of 11.

## Root causes found (one deterministic root cause explains three separate misses)

1. compute_amount_owed() / _amount_owed_block() sum every confirmed/matched invoice
   unconditionally (services/document_comparison.py:1278, agents/query_agent.py:6245).
   No filter excludes status == "PAID"; no rule picks exactly one of two candidates
   offered for an ambiguous match. This is the single mechanism behind turns 1, 3 and 11
   all producing an inflated "amount owed" that double-counts a paid or duplicate invoice.
   Proposed fix (not applied): _amount_owed_block should drop invoice terms whose
   status == "PAID" before calling compute_amount_owed, and where more than one
   candidate resolves to the "same claim" (identical line + counterparty), the resolution
   rule described in README section 3 (open status wins, most recent date wins) should
   pick one term, not sum all.

2. reconcile_referenced_documents()'s reverse-direction filter uses party_name as
   extracted, with no notion of "which side is us" (services/document_comparison.py:1115).
   For a REMITTANCE_ADVICE where the tenant is the payer ("From: Vishwa Precision
   Industries... To: Om Stationery Mart"), party_name extracted as the tenant itself
   ("Vishwa Precision Industries Pvt Ltd" -- verified against the raw PDF text, which
   prints VPI under "From" and the vendor under "To"). Since no invoice's
   vendor_name/customer_name ever equals the tenant's own name, the party_name
   filter never excludes anything, so unreferenced_invoices returns literally every
   open invoice tenant-wide (all 10 OUTBOUND receivables shown here) -- and the one
   invoice that mattered (OM-2001 for turn 7, BHA-2003 for turn 8, SHR-2005/2006 for
   turn 9) is either buried in an irrelevant list or silently dropped by the [:10]
   slice in agents/query_agent.py:7125 before the correct answer could even appear.
   Proposed fix (not applied): REMITTANCE_ADVICE/payment-advice extraction should set
   party_name to the payee (the "To" party), not the payer, when the payer is the
   tenant itself; separately, the [:10] truncation should prioritize invoices sharing
   the same vendor/customer as the attachment over an unbounded tenant-wide list.

3. Chat-attachment extraction returns items: [] for a delivery challan that has a
   clear 3-line table (turn 6, DC-BHF-0455). Verified against the source PDF text
   (dumped via pypdf) -- the table is present and unambiguous. po_number extracted
   correctly from the same document, so this is not a wholesale OCR failure, only the
   line-item table. Root cause not further isolated (would need the raw Doc Intelligence
   response, not captured here). Filed for investigation.

4. BANK_STATEMENT extraction does not populate referenced_documents (or
   statement_lines) even when narration text names invoice numbers and UTRs verbatim
   (turn 10). _run_attachment_reconcile_branch (agents/query_agent.py:7002) hard-bails
   with "I could not read a list of invoice references" whenever referenced_documents
   is empty, regardless of what items[] holds. Since the extraction schema for
   BANK_STATEMENT evidently puts everything into items[].description as free text
   rather than into referenced_documents, this document type can never reach the
   reconcile branch's happy path as currently wired.

5. Ambiguous "read vs compare" card can be returned before match candidates exist
   (turns 2, 5). Both attachments (PO-VPI-1042/GBP, DC-NMT-2291/NAT) show
   candidate_invoice_ids == [] in the immediate post-extraction row, then non-empty
   candidates minutes later (5288549a.../33d6ccd5... for GBP; 86f1559a.../
   22490a93... for NAT) once some async matching step finishes. A user (or the FE) who
   responds "compare" right after seeing the card, in the same turn-by-turn cadence this
   probe used, gets stuck on the same ambiguous prompt because candidates are not there
   yet -- there is no visible "still matching, wait" state, and the two are
   indistinguishable in the UI.

## DB verification (turn 11's "no aggregate moves")

Before and after all 11 turns (unchanged both times):
```
INBOUND:  14 invoices, sum(grand_total) = 1,891,327.60
OUTBOUND: 12 invoices, sum(grand_total) = 5,248,631.00
Bharat Hardware & Fasteners: 2 invoices, sum(grand_total) = 206,382.00
count(invoice WHERE invoice_number ILIKE CN-2010 OR BHF-CN) = 0
```
No Invoice row was created for the credit note at any point. Feature 26 D2/D3's
contract holds at the database level even though the chat answer's own net-owed
figure (163,607) is wrong (see root cause 1).

## Things that went right, worth naming

- Turn 4 is a clean match against the README with no caveats.
- No case here of a correct, praiseworthy abstention -- every abstention observed
  (turns 2, 5, 10) was a genuine capability gap, not a correct refusal.
- po_number extraction was correct on both delivery challans that cite an unlisted
  PO (PO-VPI-1039 for NAT, PO-VPI-1040 for BHA), which is the raw material the
  README's NOT_CHECKED order-leg answer needs -- the extraction layer did its job even
  where the chat layer (turn 5) and the item-table extraction (turn 6) did not.
- Duplicate invoices (RAJ-2009, and implicitly NAT-2007) were correctly identified as
  AUDIT_REQUIRED / flagged in every turn that touched them (1, 3, 4) -- the failure is
  always in what the narration does with that fact afterward (still sums it into "owed"),
  never in detecting it.
- The credit note's own candidate resolution (offering both BHA-2002 and BHA-2003, the
  correct ambiguity per README section 3) is the right behavior; the bug is downstream
  of that, in the summation.

## Reasoning-shown-was-wrong cases

Turn 11's answer explicitly states "BHA-2002 is marked PAID, but it is included in the
computed net" -- i.e. it shows correct awareness of the anomaly in its own prose while
still returning the wrong number. This is worse than a silent miss: a user reading the
caveat could reasonably conclude the number already accounts for it.

## Files

- run_vpi_turns.py -- the probe script (11 fresh sessions, poll-to-EXTRACTED, ask,
  auto-confirm-and-reask once on the ambiguous card).
- 11_turns_transcript.txt -- console transcript of the clean run (post-worker-fix).
- 11_turns_raw_bubbles.json -- full raw response payloads per turn, including the
  reconciliation / amount_owed JSON blocks quoted above.
