# VPI demo chat scenarios -- full run, 2026-09-20

Founder ask (2026-09-20): send all the chats proposed in the VPI demo README
(showcase/vpi_demo/README.md) with the results they gave -- both simple chat
(section 6, 20 questions) and chat with attachments (section 5, 11 turns) and
the docs' details in chunks. Also: what extraction would have done for the 26
invoices already in the tenant.

Scope note: section 8 (Feature 33 / ATLAS scenario) was explicitly excluded,
per instruction. Another agent is actively editing services/atlas_*,
agents/atlas_*, routers/atlas.py and the ATLAS tracker/spec files in this
branch (feature/atlas-intelligence) -- none of those files were read or
touched by this task; this evidence run only reads chat/attachment/invoice
code paths and writes under docs/test_evidence/.

## How this was run

- Local stack: Postgres 127.0.0.1:5433/invoice_db, Redis localhost:6379,
  Azurite (queue), Chroma at localhost:8001, all already running via docker
  compose (invoice-postgres-local etc.).
- uvicorn was NOT running at task start -- started it: python -m uvicorn
  main:app --host 127.0.0.1 --port 8000 (background), confirmed with a 200 on
  /docs.
- The queue worker was NOT running either -- started it: python -m
  queue_worker.main_worker (background). Without it, chat attachments sit at
  extraction_status=PENDING forever (this exact failure mode was already
  documented in vpi_demo_attachments_2026-09-19/README.md and was checked for
  here before trusting any attachment result).
- Both processes were left running at the end of the session.
- VPI tenant 00000000-0000-0000-0000-000000000000, admin user
  74d4e74d-9baa-4d7b-a651-918b44efde67, existing 26-invoice dataset. Verified
  unchanged before and after every part of this run (14 INBOUND /
  1,891,327.60, 12 OUTBOUND / 5,248,631.00, Bharat Hardware and Fasteners 2 /
  206,382.00, zero Invoice rows for the credit note). Nothing was reseeded,
  nothing was marked paid, no invoice rows were created or modified by this
  task.
- All new chat sessions are named vpi-evidence-2026-09-20-q20 (the 20-question
  walkthrough, one session, 20 sequential turns) and
  vpi-evidence-2026-09-20-attach1 through attach11 (one fresh session per
  attachment turn, matching the README's own "ask each with the file
  attached" pattern).
- Scripts (httpx against the real API, sync=true so results return inline):
  run_20_questions.py and run_11_turns.py, both adapted from the prior day's
  run_vpi_turns.py in vpi_demo_attachments_2026-09-19/ (same pattern: attach,
  poll extraction_status to terminal, ask the README's exact question,
  auto-confirm the "which one" card once if it appears). Full transcripts are
  raw_chat.json and raw_attachments.json in this folder.
- Real Azure OpenAI (Luna) and real Document Intelligence were used
  throughout, per .env -- no mocks.
- extraction_26_invoices.md was produced by a read-only Postgres query
  (no re-extraction, no invoices touched).

## Environment fact that changes grading: the as_of drift

showcase/vpi_demo/README.md section 6 freezes as_of = 2026-09-15 for every
date-dependent figure. This run executed for real on 2026-09-20 -- 5 days
later, so every due date that was "due that day" on 15-Sep is now genuinely
overdue. Questions 5, 9, 11 and 19 are graded against what the correct answer
would be today, not against the README's frozen prose (see
chat_20_questions.md for the per-row detail). This is an environment fact, not
a product defect.

## Scores

- 20-question chat walkthrough (section 6): 7 MATCH / 5 PARTIAL / 8 MISS out
  of 20. See chat_20_questions.md.
- 11-turn attachment walkthrough (section 5): 2 MATCH / 3 PARTIAL / 6 MISS out
  of 11. See attachment_11_turns.md.
- What extraction did (26 invoices, no chat involved): 26/26 rows MATCH on
  total; 3/3 expected alerts present (NAT-2007 and RAJ-2009 possible_duplicate,
  VPI-OUT-2014 tax_mismatch) with no unexpected alert (no inbound line-math
  alert, confirming Gap 502's contract holds). See extraction_26_invoices.md.

## Defects observed (candidates for the founder -- none filed to the tracker)

1. Duplicate invoices are named in chat answers but not excluded from
   aggregates. Every SUM/GROUP BY query that touches NAT-2007 or RAJ-2009
   counts them in, inflating the reported figure by exactly their value
   (seen in questions 1, 2, 7, 13, 18, 19 of the 20-question run). The
   possible_duplicate alert is surfaced as a footnote, never used to compute
   or offer the clean total README asks for.

2. Exact-string customer_name / vendor_name filters silently drop a real row
   instead of matching it or returning zero rows. customer_name = 'Deccan
   Machinery' dropped VPI-OUT-2023 (question 9); vendor_name = 'Om Stationery'
   dropped OM -2002 (question 17) -- both verified byte-identical to the
   filter's intended target in Postgres (Deccan Machinery Ltd, Om Stationery
   Mart). The mechanism is not fully isolated by this evidence pass (the
   displayed generated_sql does not explain why some but not all matching
   rows come back); recorded as a candidate defect, not root-caused.

3. A correct SQL query paired with a wrong or refused narration. Question 5's
   query already filtered on CURRENT_DATE and returned exactly the correct
   overdue set; the answer text still claimed it "can't tell" without a
   reference date. Question 20 computed a real number over the wrong scope
   (tenant-wide instead of inbound-only, no CGST/SGST split, no mention of
   the IGST/inter-state compliance finding the demo README calls out by
   name).

4. Ambiguity the README explicitly tests for is not surfaced. GBP-2012 is
   never mentioned alongside GBP-2011 (question 12); the fiscal year is never
   resolved to FY 2026-27 on its own, instead asking the user to define it
   (question 18); "how much is outstanding" is answered with a single number
   instead of asking payables-or-receivables (question 19).

5. Recurrence of five of the six defects already found and evidenced on
   2026-09-19 (Gaps 707-711, deleted from the tracker on 2026-09-20 per
   instruction, expected to recur and confirmed to do so):
   - REMITTANCE_ADVICE party_name reverse-direction bug (attachment turns
     7, 8, 9): the tenant's own name lands in party_name, so the
     "unreferenced invoice" filter can't exclude anything and dumps every
     open OUTBOUND invoice tenant-wide instead of the one open payable the
     question needs.
   - compute_amount_owed summing a PAID invoice as a positive term
     unconditionally (attachment turn 11): the credit note answer gives INR
     163,607 instead of the expected 60,416, because BHA-2002 (PAID) is
     summed alongside BHA-2003 (open) with no exclusion.
   - BANK_STATEMENT extraction never populating referenced_documents or
     statement_lines even when the narration text names invoice numbers and
     UTRs verbatim (attachment turn 10): the reconcile branch still hard-bails
     with "I could not read a list of invoice references" despite all 12
     narration lines sitting correctly extracted in items.
   - Ambiguous "couldn't write up the result" / total non-answer on a
     delivery-challan comparison with clean underlying extraction (attachment
     turn 5, DC-NMT-2291) -- same class of chat-layer failure as the
     "read or compare" card defect from 2026-09-19, different symptom text.
   One defect from 2026-09-19 did NOT recur: turn 6's empty-items extraction
   failure on DC-BHF-0455 is fixed -- all 3 line items extract correctly
   today. Turn 2's ambiguous-card defect on PO-VPI-1042/GBP also did not
   recur -- today's run correctly compared both GBP-2011 and GBP-2012 against
   the PO in one pass.

6. New finding, not in the 2026-09-19 evidence: attachment turn 8's doc_type
   is stored as REMISSION_ADVICE, not REMITTANCE_ADVICE like turns 7 and 9
   for the identically-generated document family (a payment-advice PDF from
   the same generator). The Chroma chunk header for the same attachment
   correctly reads REMITTANCE_ADVICE, so the misspelling/taxonomy drift
   exists only in the chat_attachments.doc_type column, not in what was
   indexed for retrieval. See attachment_chunks.md turn 8.

7. New finding: attachment turn 4's nested extracted_json.doc_type field
   reads OTHER while the chat_attachments row's own doc_type column reads
   DELIVERY_NOTE for the same attachment -- an internal inconsistency between
   the row-level classification and the payload's own doc_type field. See
   attachment_chunks.md turn 4.

## Files in this folder

- chat_20_questions.md -- section 6 grading table, session id, generated SQL
  per question, verdicts.
- attachment_11_turns.md -- section 5 grading table plus the per-attachment
  extraction detail table (doc type, extraction_status, referenced_documents,
  items/statement_lines count, candidate_invoice_ids).
- attachment_chunks.md -- what was stored for retrieval per attachment:
  extracted_json essentials and the actual Chroma chunk(s) queried live from
  chat_docs_00000000-0000-0000-0000-000000000000.
- extraction_26_invoices.md -- what extraction did for the 26 invoices already
  in the tenant, read from Postgres only, graded against README section 3.
- raw_chat.json -- full request/response payloads for the 20-question run.
- raw_attachments.json -- full request/response payloads for the 11-turn run.
