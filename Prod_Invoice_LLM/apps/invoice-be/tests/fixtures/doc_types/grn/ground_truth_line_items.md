# Ground Truth -- GRN fixtures (Feature 27 Task F, Dispatch B)

Source PDF: `../grn/india_inbound/IN-GRN-01_goods_receipt_note.pdf` -- 1 file, synthetic (see
`../MANIFEST.md`). India-only per section 7's own table (`GRN` row: India Yes, EU/US n/a --
"not a standard externally-exchanged commercial document," E4). Realistic synthetic is
explicitly acceptable and expected per E4 ("a real sample cannot be obtained" for this
low-frequency, internal-origin type). QUANTITY family (same as DELIVERY_NOTE).

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Prices printed |
|---|---|---|---|---|---|
| IN-GRN-01_goods_receipt_note.pdf | India | GOODS RECEIPT NOTE | GRN | Quantity | No |

## Flat line-item table

| File | Line Description | Qty Ordered | Qty Received | UOM | Remarks |
|---|---|---|---|---|---|
| IN-GRN-01 | CNC Machined Bracket - Type A | 250 | 250 | Nos | OK |
| IN-GRN-01 | CNC Machined Bracket - Type B | 120 | **110** | Nos | Short by 10 -- 2 damaged, 8 not loaded |
| IN-GRN-01 | Mounting Plate Assembly | 60 | 60 | Nos | OK |

Line 2's Qty Ordered != Qty Received mismatch is **deliberate**, not a data-entry error --
per E4's stated real-world appearance of a GRN ("shared with a supplier to substantiate a
short-delivery or damage claim"), this is the realistic case, not a schematic all-matching
placeholder. A classifier/extraction consumer must not treat this quantity mismatch as an
arithmetic (money) discrepancy -- it is the document's actual, correct content.

## Header fields (not per-line, repeated per document)

- IN-GRN-01: Issuer (buyer's own Stores and Warehouse Department) Infinevo Cloud Pvt Ltd,
  GSTIN 06AABCI5678F1Z9. Supplier Ashoka Precision Components Pvt Ltd, GSTIN
  27AAJCA9988P1Z3. GRN No GRN-2026-0341, GRN Date 2026-08-15, PO Reference PO-IN-6102,
  Delivery Challan Reference DC-2026-0871 (the exact challan number used in
  `../delivery_note/india_inbound/IN-DN-01`, a deliberate continuity: this GRN represents the
  buyer's internal receipt of that same shipment), Vehicle No MH-12-AB-4471. No subtotal, no
  tax, no grand total printed -- correct and expected (GRN is internal-origin and has no
  commercial value of its own).

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1: "GOODS RECEIPT NOTE" is an exact `_DOC_TYPE_SYNONYMS` entry -- classifies via the
  deterministic pass. **Confirmed against the real classifier, 2026-09-02**:
  `doc_type_method=deterministic`, `doc_type_confidence=1.0` (see `../MANIFEST.md`).
- E4/E6 QUANTITY family: price fields absent by design, not a discrepancy; the Qty
  Ordered/Received mismatch on Line 2 is content, not an alert-worthy anomaly for the
  arithmetic rubric (it would only be relevant to a future matching/reconciliation feature
  that compares GRN quantities against the PO/challan, which is explicitly out of this
  feature's scope).
- Low real-world GRN frequency is expected and, per E4, is "not a classifier defect" -- this
  single fixture is the deliberately-accepted minimum bar for the cell, not an
  under-investment relative to the other types.

## Data-quality flags

None on the data that is present. Deliberately carries one internal quantity discrepancy
(Line 2) as realistic content, not a defect -- see above. No erroneous-GRN variant (e.g. a
GRN with an internally inconsistent Qty Ordered vs. the referenced PO's own quantity) built
this pass; flagged as a real gap for the taxonomy wave, not an oversight.
