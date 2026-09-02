# Ground Truth -- PURCHASE_ORDER fixtures (Feature 27 Task F, Dispatch B)

Source PDFs: `../purchase_order/{india_inbound,us_inbound}/` -- 2 files, both synthetic (see
`../MANIFEST.md`). One defensible sample per region per the dispatch-B budget (not the full
3-region matrix section 7's own table lists -- that is the taxonomy wave's job later).
COMMITMENT family (E4 / `document_type_classifier.DOC_TYPE_FAMILY`): unlike CONTRACT, a
commercial PO conventionally states its own order value, so both fixtures here DO carry a
printed grand total and are internally arithmetically consistent (qty x rate = amount,
subtotal + tax = grand total).

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Grand total printed |
|---|---|---|---|---|---|
| IN-PO-01_purchase_order.pdf | India | PURCHASE ORDER | PURCHASE_ORDER | Commitment | Yes (Rs 10,44,300.00) |
| US-PO-01_purchase_order.pdf | US | PURCHASE ORDER | PURCHASE_ORDER | Commitment | Yes ($34,611.50) |

## Flat line-item table

| File | Line Description | Qty | Rate/Unit Price | Amount | HSN/Ship Date |
|---|---|---|---|---|---|
| IN-PO-01 | Forged Steel Flange - 6 inch | 400 | Rs 1,150.00 | Rs 4,60,000.00 | HSN 7326 |
| IN-PO-01 | Forged Steel Flange - 8 inch | 250 | Rs 1,700.00 | Rs 4,25,000.00 | HSN 7326 |
| US-PO-01 | Industrial Conveyor Belt, Model CB-500 | 10 | $2,450.00 | $24,500.00 | Requested ship 09/20/2026 |
| US-PO-01 | Replacement Roller Assembly | 40 | $185.00 | $7,400.00 | Requested ship 10/05/2026 |

## Header fields (not per-line, repeated per document)

- IN-PO-01: Buyer Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Vendor Vishwakarma Forgings
  Ltd, GSTIN 06AAECV4321R1Z8. PO No PO-IN-6102, PO Date 2026-07-28, Vendor Ref QTN-IN-2214,
  Delivery Terms FOB Pune within 3 weeks, Payment Terms 30 days from Tax Invoice. Subtotal
  Rs 8,85,000.00, GST 18 percent Rs 1,59,300.00, Order Value (Grand Total) Rs 10,44,300.00.
- US-PO-01: Buyer Northgate Manufacturing Inc., EIN 74-1029384. Vendor Cascade Industrial
  Supply LLC. PO No PO-US-8841, PO Date 08/12/2026, Incoterms FOB Origin, Payment Terms Net
  45. Two distinct requested ship dates (delivery schedule, the COMMITMENT-family shape E4
  describes). Subtotal $31,900.00, Sales Tax 8.5 percent $2,711.50, Order Total (Grand
  Total) $34,611.50.

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1: "PURCHASE ORDER" is an exact `_DOC_TYPE_SYNONYMS` entry -- both fixtures classify
  via the deterministic pass, no LLM call. **Confirmed against the real classifier,
  2026-09-02** (see `../MANIFEST.md` confidence column): both `doc_type_method=deterministic`,
  `doc_type_confidence=1.0`.
- E4/E6 COMMITMENT family: "arithmetic checks run where totals are printed" -- unlike
  CONTRACT, both POs here DO print and reconcile a grand total, so full arithmetic
  verification is expected to pass once G5's rubric lands.
- A `document_type_classifier.py` naming note (see module docstring, "naming note 2") flags
  QUOTATION's COMMITMENT-family assignment as provisional/founder-unconfirmed; PURCHASE_ORDER
  is not flagged that way and is treated as settled COMMITMENT.

## Data-quality flags

None. Both fixtures are internally consistent by construction (synthetic, no seeded
defects). No erroneous-PURCHASE_ORDER variant built this pass; flagged as a real gap for the
taxonomy wave, not an oversight.
