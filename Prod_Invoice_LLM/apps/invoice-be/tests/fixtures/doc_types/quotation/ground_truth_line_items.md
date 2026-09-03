# Ground Truth -- QUOTATION fixtures (Feature 27 Task F, Dispatch B)

Source PDF: `../quotation/india_inbound/IN-QT-01_quotation.pdf` -- 1 file, synthetic (see
`../MANIFEST.md`). One defensible sample per the dispatch-B budget (India only this pass;
EU/US left for the taxonomy wave). Family: mapped to COMMITMENT in
`document_type_classifier.DOC_TYPE_FAMILY`, but flagged there as **provisional and
founder-unconfirmed** ("naming note 2" in the module docstring) -- not settled the way
PURCHASE_ORDER/CONTRACT are.

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4, provisional) | Grand total printed |
|---|---|---|---|---|---|
| IN-QT-01_quotation.pdf | India | QUOTATION | QUOTATION | Commitment (provisional) | Yes, but explicitly labelled "Indicative" throughout |

**Structural distinguisher from PROFORMA_INVOICE** (section 7's explicit warning for the
proforma cell, applied here in reverse): this fixture is an open-ended offer -- no committed
buyer PO reference exists anywhere on the document, and every price/total is qualified
"Indicative" / "subject to change without notice" / "subject to confirmation at the time a
Purchase Order is placed." A genuine proforma (see `../proforma_invoice/`) instead carries a
committed buyer PO reference and an advance-payment/LC mechanism. Losing that distinction
either direction (a quotation printed as if committed, or a proforma printed as if
open-ended) would be a realism defect, not merely a labelling one.

## Flat line-item table

| File | Line Description | Qty (Indicative) | Unit Price | Amount |
|---|---|---|---|---|
| IN-QT-01 | Hydraulic Cylinder Assembly HC-250 | 50 | Rs 3,200.00 | Rs 1,60,000.00 |
| IN-QT-01 | Seal Kit HC-250 | 50 | Rs 450.00 | Rs 22,500.00 |

## Header fields (not per-line, repeated per document)

- IN-QT-01: Vendor Vishwakarma Forgings Ltd, GSTIN 06AAECV4321R1Z8. Prospective buyer
  Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Quotation No QTN-IN-2214, Date 2026-07-20,
  Validity 15 days, issued "in response to your RFQ dated 2026-07-15" (an inbound RFQ, not a
  committed PO). Subtotal (Indicative) Rs 1,82,500.00, GST 18 percent (Indicative)
  Rs 32,850.00, Total (Indicative) Rs 2,15,350.00.

Note the deliberate continuity: this quotation's vendor (Vishwakarma Forgings Ltd) and buyer
(Infinevo Cloud Pvt Ltd) are the same pair used in `../purchase_order/india_inbound/IN-PO-01`
and `../contract/india_inbound/IN-CT-01`, with the same item family (forged/machined
components) at different prices -- a deliberate continuity across the fixture set so a future
matching/reconciliation feature has a realistic chain to walk (quote -> PO -> rate contract),
per E4's stated commercial-lifecycle ordering, without the numbers actually reconciling
across documents (they were generated independently and are not meant to match line for
line).

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1: "QUOTATION" is an exact `_DOC_TYPE_SYNONYMS` entry -- classifies via the
  deterministic pass. **Confirmed against the real classifier, 2026-09-02**:
  `doc_type_method=deterministic`, `doc_type_confidence=1.0` (see `../MANIFEST.md`).
- Open item for whoever builds G5's rubric map: this fixture is real evidence that a
  QUOTATION can print a fully-reconciling subtotal/tax/total (arithmetically consistent by
  construction here), so if QUOTATION's family assignment is later confirmed as COMMITMENT
  rather than MONEY, the rubric must still tolerate it when a quotation legitimately omits
  pricing on some lines -- this fixture alone does not exercise that partial-pricing case.

## Data-quality flags

None. Internally consistent by construction (synthetic, no seeded defects). No
erroneous-QUOTATION variant or EU/US regional variant built this pass; flagged as a real gap
for the taxonomy wave, not an oversight.
