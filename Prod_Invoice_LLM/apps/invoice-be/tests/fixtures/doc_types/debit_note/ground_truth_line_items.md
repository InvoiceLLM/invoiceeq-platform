# Ground Truth -- DEBIT_NOTE fixtures (Feature 27 Task F, Dispatch B)

Source PDF: `../debit_note/india_inbound/IN-DB-01_debit_note.pdf` -- 1 file, synthetic (see
`../MANIFEST.md`). One defensible sample per the dispatch-B budget (India only this pass).
Mirror-image counterpart to `../credit_note/`'s fixture (price escalation against an original
invoice, rather than a return). MONEY family (E4).

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Grand total printed |
|---|---|---|---|---|---|
| IN-DB-01_debit_note.pdf | India | DEBIT NOTE | DEBIT_NOTE | Money | Yes (Rs 21,240.00, labelled "Total Debit Amount") |

## Flat line-item table

| File | Line Description | Qty | Additional Rate | Amount |
|---|---|---|---|---|
| IN-DB-01 | Forged Steel Flange - 6 inch (price escalation) | 400 | Rs 45.00 | Rs 18,000.00 |

Internally consistent: 400 x Rs 45.00 = Rs 18,000.00 exactly; Subtotal Rs 18,000.00 + GST 18
percent (Rs 3,240.00) = Rs 21,240.00 exactly.

## Header fields (not per-line, repeated per document)

- IN-DB-01: Issuer (buyer, debiting the vendor for a shortfall) Infinevo Cloud Pvt Ltd, GSTIN
  06AABCI5678F1Z9. Issued To (vendor) Vishwakarma Forgings Ltd, GSTIN 06AAECV4321R1Z8. Debit
  Note No DN-2026-0053, Date 2026-08-30. Against Original Tax Invoice No INV-2026-0512 dated
  2026-08-22 (a distinct invoice number from the credit note's, since the two adjustment
  types apply to different underlying transactions by design). Reason for Debit: "Price
  escalation -- raw material cost increase per agreed Rate Contract clause 4.2" -- a
  deliberate reference to `../contract/india_inbound/IN-CT-01`'s Rate Contract mechanism
  (cross-fixture continuity: the rate contract's per-unit rates are exactly what this debit
  note is escalating). Explicit statutory citation: "issued under Section 34(3) of the CGST
  Act, 2017."

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1: "DEBIT NOTE" is an exact `_DOC_TYPE_SYNONYMS` entry -- classifies via the
  deterministic pass. **Confirmed against the real classifier, 2026-09-02**:
  `doc_type_method=deterministic`, `doc_type_confidence=1.0` (see `../MANIFEST.md`).
- E4/E6 MONEY family: full existing arithmetic verification applies unchanged, same reasoning
  as the credit-note fixture. DEBIT_NOTE is one of the four INVOICE-family types kept on
  `InvoiceExtractionSchema`/`_DIRECTION_PROFILES` per A2, never routed to the generic profile.

## Data-quality flags

None. Internally consistent by construction (synthetic, no seeded defects). No
erroneous-DEBIT_NOTE variant or EU/US regional variant built this pass; flagged as a real gap
for the taxonomy wave, not an oversight.
