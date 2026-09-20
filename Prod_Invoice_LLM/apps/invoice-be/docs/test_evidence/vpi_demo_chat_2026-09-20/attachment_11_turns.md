# VPI demo -- 11 chat-attachment turns vs README section 5 ground truth (2026-09-20)

Real local stack: uvicorn on 127.0.0.1:8000, Postgres 127.0.0.1:5433 (invoice_db),
real Azure OpenAI (Luna), real Document Intelligence. VPI tenant
00000000-0000-0000-0000-000000000000, existing 26-invoice dataset (verified
unchanged before and after -- see DB verification below). One fresh chat
session per turn, titled vpi-evidence-2026-09-20-attach{N}. Files come from
showcase/vpi_demo/upload/ (turns 1-10) and showcase/vpi_demo/invoices_pdf/
(turn 11, the credit note). Full request/response payloads: raw_attachments.json.

Environment: the queue worker (queue_worker/main_worker.py) was not running at
task start -- started it explicitly (python -m queue_worker.main_worker) before
this run; without it, chat attachments sit at extraction_status=PENDING forever
(confirmed by the prior day's evidence run in vpi_demo_attachments_2026-09-19/).
Both uvicorn and the worker were left running at the end of this session.

Founder note: Gaps 707-711 (the defects this same probe found on 2026-09-19)
were deleted from the tracker on 2026-09-20 per instruction, so their symptoms
are expected to recur here -- and five of six do (see verdicts and root causes
below), confirming they were never actually fixed.

## Turn-by-turn grading

| # | Attach | Ask | Verdict | Notes |
|---|---|---|---|---|
| 1 | PO-VPI-1041 (RAJ) | Does this PO match the Rajesh Steel invoice? | PARTIAL | Correctly matches PO to both RAJ-2008 and RAJ-2009 line-by-line (437,190 = PO total), correctly flags RAJ-2009 AUDIT_REQUIRED as a possible duplicate -- but appends "treating both invoices as payable produces a computed net of INR 874,380.0", a confusing double-counted framing the question never asked for. |
| 2 | PO-VPI-1042 (GBP) | Is the Ganesh Bearings invoice within this PO? | MATCH | GBP-2011 correctly matched line-for-line (68,676 = PO); GBP-2012 correctly identified as outside the PO (higher total, different items). Clear improvement over the 2026-09-19 run, which returned only an ambiguous "read or compare" card here. |
| 3 | PO-VPI-1043 (SHR) | Compare with Shree Packaging's August invoice | PARTIAL | Correctly compared SHR-2005 (exact match) and correctly found a real variance on SHR-2006 (826.00 higher, missing wooden pallets) -- but never compares against SHR-2004 (the already-paid July invoice with identical lines) that README explicitly requires be named as the other candidate. |
| 4 | DC-RSC-0812 (RAJ) | Was everything on this challan invoiced? | MATCH | 6 coils + 30 bars correctly matched to both RAJ-2008 and RAJ-2009; correctly flags RAJ-2009 as a duplicate and quotes the challan's own "as per invoice RAJ-2008" text. |
| 5 | DC-NMT-2291 (NAT) | Check delivery against invoice | MISS | "I compared the documents but couldn't write up the result. Try asking again." -- total failure, no comparison content at all, despite the DB row showing clean extraction (5/12/8 items, PO-VPI-1039 captured, candidates correctly populated). Same failure mode as the 2026-09-19 run's turn 5. |
| 6 | DC-BHF-0455 (BHA) | Any short delivery here? | PARTIAL | Correctly reads all 3 line items (25/15/4, zero delta) -- the 2026-09-19 run's items=[] extraction defect for this exact document is NOT reproduced here (extracted_json.items now has all 3 lines). But the answer never names BHA-2003 by invoice number or notes the PO-VPI-1040-not-on-file NOT_CHECKED order leg README requires. |
| 7 | PA-VPI-0071 (OM) | Which invoice does this payment settle? | MISS | Correctly matches OM -2000 (41,654, PAID, agrees) but then lists all 10 open OUTBOUND receivables (Kaveri/Sunrise/Deccan) as "not listed on their document" and never mentions OM -2001, the one payable the question needs. Same root cause as 2026-09-19 (party_name reverse-direction bug on REMITTANCE_ADVICE, still present). |
| 8 | PA-VPI-0072 (BHA) | Is Bharat Hardware fully paid? | MISS | States "Yes, fully paid" citing only BHA-2002 (103,191, matches remittance) -- never checks or mentions BHA-2003 (open, 103,191), so the literal answer given is wrong. |
| 9 | PA-VPI-0073 (SHR) | What do we still owe Shree Packaging? | MISS | Correctly settles SHR-2004 (paid), then lists the same 10 irrelevant OUTBOUND invoices instead of SHR-2005/SHR-2006 (the actual open payables, 244,614 combined); explicitly states "a combined outstanding total was not returned ... I have not calculated one." |
| 10 | BankStatement_HDFC_4471_Aug2026 | Match this statement to our books | MISS | "I could not read a list of invoice references off that document, so there is nothing for me to reconcile" -- despite extracted_json.items holding all 12 narration lines verbatim (OM -2000/BHA-2002/SHR-2004 debits, the 200,000 Deccan credit, GST/electricity/salary/AMC/charges, closing balance 355,336.00 all present in the row). referenced_documents and statement_lines are both empty -- same root cause as 2026-09-19 (BANK_STATEMENT extraction never maps items into referenced_documents). |
| 11 | Credit note BHF-CN-2010 | Bharat sent this - what do we actually owe them? | MISS | Correctly surfaces both BHA-2002 and BHA-2003 as candidates (the right ambiguity) and correctly confirms both -- but then sums the credit note (-42,775) with BOTH invoices as positive terms (103,191 + 103,191), giving INR 163,607, despite BHA-2002 being marked PAID. Expected: resolve to BHA-2003 only, net 60,416. Same root cause as 2026-09-19 (no PAID exclusion in the amount-owed computation). |

## Score

2 MATCH / 3 PARTIAL / 6 MISS out of 11 (2, 4 MATCH; 1, 3, 6 PARTIAL; 5, 7, 8, 9, 10, 11 MISS).

## DB verification (no aggregate moves, no reseed)

Before and after all 11 turns, queried directly against Postgres:
- INBOUND: 14 invoices, sum(grand_total) = 1,891,327.60 (unchanged)
- OUTBOUND: 12 invoices, sum(grand_total) = 5,248,631.00 (unchanged)
- Bharat Hardware and Fasteners: 2 invoices, sum(grand_total) = 206,382.00 (unchanged)
- count(invoice WHERE invoice_number ILIKE '%CN-2010%' OR '%BHF-CN%') = 0 -- no Invoice row was ever created for the credit note

Feature 26 D2/D3's "no aggregate moves" contract holds at the database level in
this run, exactly as it did on 2026-09-19, even though turn 11's own arithmetic
is wrong (see above).

## Attachment extraction detail (per row, from Postgres chat_attachments)

| # | attachment id | doc_type | extraction_status | referenced_documents | items / statement_lines count | candidate_invoice_ids |
|---|---|---|---|---|---|---|
| 1 | 06397de2-1c0d-4216-8607-ae105fd4d6e0 | PURCHASE_ORDER | EXTRACTED | 0 | items=2 | [d5869da2 (RAJ-2008), 530bd65a (RAJ-2009)] |
| 2 | ba1b01f5-e74e-47e8-a6cc-6fe73f958e6a | PURCHASE_ORDER | EXTRACTED | 0 | items=2 | [5288549a (GBP-2011), 33d6ccd5 (GBP-2012)] |
| 3 | f87c3e0c-1f2a-4961-8d33-05a29405f391 | PURCHASE_ORDER | EXTRACTED | 0 | items=3 | [29a03885 (SHR-2004), 11c3df22 (SHR-2006), fbe08368 (SHR-2005)] |
| 4 | e016464b-1c3d-4ec4-b2e1-d0ca983ea0a1 | DELIVERY_NOTE | EXTRACTED | 0 | items=2 | [d5869da2 (RAJ-2008), 530bd65a (RAJ-2009)] |
| 5 | 091cd819-cb17-4f56-8cc3-62c86c102e3f | DELIVERY_NOTE | EXTRACTED | 0 | items=3 | [86f1559a (NAT-2006), 22490a93 (NAT-2007)] |
| 6 | d673729e-c259-4c14-8203-988fc2c5c290 | DELIVERY_NOTE | EXTRACTED | 0 | items=3 | [d0a5d0dd (BHA-2003), b96f4a85 (BHA-2002)] |
| 7 | a201841b-e050-40d7-afd7-a1a766f70ad4 | REMITTANCE_ADVICE | EXTRACTED | 1 (OM -2000, 41,654.00) | items=0 | 12 candidates -- every OUTBOUND invoice tenant-wide, not scoped to Om Stationery |
| 8 | ee4104df-516d-4671-9345-ac2d829b85bc | REMISSION_ADVICE (sic -- doc_type value literally stored this way, not REMITTANCE_ADVICE like turns 7 and 9) | EXTRACTED | 1 (BHA-2002, 103,191.00) | items=0 | 12 candidates -- same tenant-wide list |
| 9 | 7aba353f-3110-4193-a348-15417a60ed0b | REMITTANCE_ADVICE | EXTRACTED | 1 (SHR-2004, 121,894.00) | items=0 | 12 candidates -- same tenant-wide list |
| 10 | c62bc887-eeee-4cea-84ec-01a52b1f45b4 | BANK_STATEMENT | EXTRACTED | 0 | items=12 (all narration lines) | [] (empty -- reconcile branch never runs) |
| 11 | 24fea591-4f05-4105-9c58-b90ef811f196 | CREDIT_NOTE | EXTRACTED | 1 (empty stub -- no doc_number/amount/date) | items=1 | [d0a5d0dd (BHA-2003), b96f4a85 (BHA-2002)] |

Doc-type note (turn 8): the stored value is REMISSION_ADVICE, not REMITTANCE_ADVICE
like turns 7 and 9 for the same document family (a payment-advice PDF built by
the same generator) -- a spelling/taxonomy inconsistency, not a comparison
defect, filed as a candidate finding in README.md.
