# What was stored for retrieval -- 11 chat attachments, 2026-09-20

Two independent stores are checked here, per attachment:

1. chat_attachments.extracted_json (Postgres) -- the ~15 denormalised fields
   (doc number, party, totals, line items) used by the comparison/reconciliation
   branch.
2. Chroma -- chat attachments ARE chunked into the vector store. Confirmed in
   code: services/attachment_extraction.py lines 258-261 call
   index_attachment_chunks(row, row.tenant_id) from
   services/chat_document_search.py, which chunks one PDF page per chunk,
   writes ids {attachment_id}_page_{n} into collection
   chat_docs_{tenant_id} (never invoice_chunks_{tenant_id} -- see the
   module docstring's stated reason: keeping a quoted, not-billed price out of
   the RAG route's invoice-chunk context), and upserts (re-indexing the same
   attachment replaces its chunks, no duplication). Queried directly against
   the live collection for this run:

collection name: chat_docs_00000000-0000-0000-0000-000000000000
count: 52 (includes chunks from prior runs on this tenant; today's 11
attachments each produced exactly 1 chunk, since every source PDF in this
scenario is single-page)

Each chunk's text is NOT extracted_json -- it is the raw page text re-read
from the stored PDF via fitz, prefixed with a header:
"Document type: X | Party: Y | Document number: Z | Page N".

## Turn 1 -- PO-VPI-1041 (Rajesh Steel Corporation)

attachment id 06397de2-1c0d-4216-8607-ae105fd4d6e0

extracted_json (essentials): doc_type PURCHASE_ORDER, doc_number PO-VPI-1041,
party Rajesh Steel Corporation, doc_date 2026-08-05, subtotal 370,500.00, tax
66,690.00 (CGST 33,345 + SGST 33,345), grand_total 437,190.00, 2 items (HR
Steel Coil 2mm qty 6 at 48,500; Steel Angle Bar 2x2x1/4 20ft qty 30 at 2,650),
payment_terms Net 30, referenced_documents empty.

Chroma: 1 chunk, page 1. Header: "Document type: PURCHASE_ORDER | Party:
Rajesh Steel Corporation | Document number: PO-VPI-1041 | Page 1", followed
by the full PO page text (buyer/supplier GSTINs, line table, notes).

## Turn 2 -- PO-VPI-1042 (Ganesh Bearings Pvt Ltd)

attachment id ba1b01f5-e74e-47e8-a6cc-6fe73f958e6a

extracted_json (essentials): doc_type PURCHASE_ORDER, doc_number PO-VPI-1042,
party Ganesh Bearings Pvt Ltd, subtotal 58,200.00, tax 10,476.00, grand_total
68,676.00, 2 items (Deep Groove Ball Bearing 6205 qty 60 at 520; Tapered Roller
Bearing 30205 qty 25 at 1,080), payment_terms "Net 30 (new vendor)",
referenced_documents empty.

Chroma: 1 chunk, page 1, same header pattern.

## Turn 3 -- PO-VPI-1043 (Shree Packaging Industries)

attachment id f87c3e0c-1f2a-4961-8d33-05a29405f391

extracted_json (essentials): doc_type PURCHASE_ORDER, doc_number PO-VPI-1043,
party Shree Packaging Industries, subtotal 103,300.00, tax 18,594.00,
grand_total 121,894.00, 3 items (Corrugated Boxes 24x18x18 qty 150 at 220;
Wooden Pallets 48x40 qty 50 at 950; Stretch Wrap Film 20 rolls qty 6 at 3,800),
referenced_documents empty.

Chroma: 1 chunk, page 1.

## Turn 4 -- DC-RSC-0812 (Rajesh Steel Corporation delivery challan)

attachment id e016464b-1c3d-4ec4-b2e1-d0ca983ea0a1

extracted_json (essentials): the nested doc_type field inside extracted_json
reads OTHER (not DELIVERY_NOTE -- the chat_attachments row's own doc_type
column says DELIVERY_NOTE, so this is an internal inconsistency between the
row-level classification and the payload's own doc_type field, worth flagging),
doc_number null, po_number PO-VPI-1041, party Rajesh Steel Corporation, 2 items
with quantity but no unit_price/amount (HR Steel Coil 2mm qty 6; Steel Angle
Bar qty 30), notes cite "as per invoice RAJ-2008", referenced_documents empty.

Chroma: 1 chunk, page 1, header reads "Document number: Unknown" (doc_number
was never populated on this row).

## Turn 5 -- DC-NMT-2291 (National MRO Traders delivery challan)

attachment id 091cd819-cb17-4f56-8cc3-62c86c102e3f

extracted_json (essentials): doc_number DC-NMT-2291, po_number PO-VPI-1039
(correctly captured even though that PO is not on file), party National MRO
Traders, 3 items with quantity only (Industrial Lubricant 20L qty 5;
Replacement V-Belts qty 12; Safety Gloves case of 60 qty 8), notes cite "as per
invoice NAT-2006", referenced_documents empty.

Chroma: 1 chunk, page 1. The extraction itself is clean here -- turn 5's chat
answer failure ("I compared the documents but couldn't write up the result")
is downstream of this correct data, not caused by it.

## Turn 6 -- DC-BHF-0455 (Bharat Hardware and Fasteners delivery challan)

attachment id d673729e-c259-4c14-8203-988fc2c5c290

extracted_json (essentials): doc_number DC-BHF-0455, po_number PO-VPI-1040
(not on file), party Bharat Hardware and Fasteners, 3 items with quantity only
(Hex Bolts M10x40 box 100 qty 25; SS Washers box 500 qty 15; Torque Wrench
1/2in qty 4), notes cite "as per invoice BHA-2003", referenced_documents empty.

Chroma: 1 chunk, page 1. Note: the 2026-09-19 evidence run found items: []
for this exact document (a real extraction defect at the time); today's row
has all 3 line items populated correctly -- that specific defect did not
recur.

## Turn 7 -- PA-VPI-0071 (payment advice, Om Stationery Mart)

attachment id a201841b-e050-40d7-afd7-a1a766f70ad4

extracted_json (essentials): doc_type REMITTANCE_ADVICE, doc_number
PA-VPI-0071, party_name "Vishwa Precision Industries Pvt Ltd" (the tenant
itself -- this document's payer, not its payee), counterparty_name "Om
Stationery Mart" (the actual payee, correctly captured in a separate field),
grand_total 41,654.00, reference_numbers list contains "OM -2000",
referenced_documents has one entry (doc_number OM -2000, amount 41654.0,
doc_date 2026-07-09), items empty (payment advices carry no line items by
design). UTR HDFCN26080512345 and mode NEFT are in the free-text notes field,
not a structured field.

Chroma: 1 chunk, page 1, header correctly reads "Party: Vishwa Precision
Industries Pvt Ltd" (the same "who is this document about" ambiguity the chat
answer's root cause exploits -- see attachment_11_turns.md turn 7).

## Turn 8 -- PA-VPI-0072 (payment advice, Bharat Hardware and Fasteners)

attachment id ee4104df-516d-4671-9345-ac2d829b85bc

extracted_json (essentials): doc_type stored as REMISSION_ADVICE (not
REMITTANCE_ADVICE like turns 7 and 9 for the same document family -- a
taxonomy/spelling inconsistency), doc_number PA-VPI-0072, counterparty_name
"Bharat Hardware and Fasteners", grand_total 103,191.00, reference_numbers
list contains "BHA-2002", referenced_documents has one entry (doc_number
BHA-2002, amount 103191.0, currency INR, doc_date 2026-07-09), items empty.

Chroma: 1 chunk, page 1 -- interestingly the chunk's own header string reads
"Document type: REMITTANCE_ADVICE" (matching turns 7/9), so the
REMISSION_ADVICE spelling exists only in the Postgres doc_type column, not
in what was indexed for retrieval.

## Turn 9 -- PA-VPI-0073 (payment advice, Shree Packaging Industries)

attachment id 7aba353f-3110-4193-a348-15417a60ed0b

extracted_json (essentials): doc_type REMITTANCE_ADVICE, doc_number
PA-VPI-0073, counterparty_name "Shree Packaging Industries", grand_total
121,894.00, reference_numbers list contains "SHR-2004", referenced_documents
has one entry (doc_number SHR-2004, amount 121894.0, doc_date 2026-07-09),
items empty.

Chroma: 1 chunk, page 1.

## Turn 10 -- BankStatement_HDFC_4471_Aug2026

attachment id c62bc887-eeee-4cea-84ec-01a52b1f45b4

extracted_json (essentials): doc_type BANK_STATEMENT, party "HDFC BANK
LIMITED", grand_total (closing balance) 355,336.00, 12 items, each one
narration line stored as a free-text description with the amount in the
amount field (examples: "NEFT DR OM STATIONERY MART INV OM -2000 UTR
HDFCN26080512345" mapped to 41,654.00; "NEFT DR BHARAT HARDWARE and FASTENERS
INV BHA-2002 UTR HDFCN26080612346" mapped to 103,191.00; opening balance
1,250,000.00; GST payment 184,320.00; and more, truncated in this summary).
referenced_documents is empty and statement_lines is also empty -- the
narration text is genuinely present and readable (verbatim invoice numbers,
UTRs, amounts all in items), but nothing maps it into either structured
field, which is exactly why turn 10's chat answer abstains as if the document
were unreadable.

Chroma: 1 chunk, page 1. The full narration text (all 12 lines) is present in
the indexed chunk, so a content-search question ("what does the bank statement
say about OM -2000") would find it -- only the structured-reconciliation
branch is blind to it.

## Turn 11 -- Credit note BHF-CN-2010 (Bharat Hardware and Fasteners)

attachment id 24fea591-4f05-4105-9c58-b90ef811f196

extracted_json (essentials): doc_type CREDIT_NOTE, doc_number BHF-CN-2010,
party Bharat Hardware and Fasteners, doc_date 2026-08-17, subtotal -36,250.00,
tax -6,525.00 (CGST -3,262.50 + SGST -3,262.50), grand_total -42,775.00, 1 item
(Hex Bolts M10x40 box 100, qty 25 at 1,450, amount -36,250.00),
referenced_documents is present as a list with one entry but every field
inside it is null (doc_number, amount, doc_date all null) -- matches README
section 3's "it prints no invoice reference" exactly -- and candidate
resolution instead falls to the counterparty + identical-line + date matching
README describes, which is how both BHA-2002 and BHA-2003 end up as
candidate_invoice_ids.

Chroma: 1 chunk, page 1.
