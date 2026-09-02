# Ground Truth -- CREDIT_NOTE fixtures (Feature 27 Task F, Dispatch B)

Source PDF: `../credit_note/india_inbound/IN-CN-01_credit_note.pdf` -- 1 file, synthetic (see
`../MANIFEST.md`). One defensible sample per the dispatch-B budget (India only this pass).
MONEY family (E4) -- same full arithmetic rubric as INVOICE.

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Grand total printed |
|---|---|---|---|---|---|
| IN-CN-01_credit_note.pdf | India | CREDIT NOTE | CREDIT_NOTE | Money | Yes (Rs 43,660.00, labelled "Total Credit Amount") |

## Flat line-item table

| File | Line Description | Qty | Rate | Amount |
|---|---|---|---|---|
| IN-CN-01 | Forged Steel Flange - 8 inch (Returned) | 20 | Rs 1,850.00 | Rs 37,000.00 |

Internally consistent: 20 x Rs 1,850.00 = Rs 37,000.00 exactly; Subtotal Rs 37,000.00 + GST
Reversal 18 percent (Rs 6,660.00) = Rs 43,660.00 exactly.

## Header fields (not per-line, repeated per document)

- IN-CN-01: Issuer (original vendor) Vishwakarma Forgings Ltd, GSTIN 06AAECV4321R1Z8. Issued
  To (buyer) Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Credit Note No CN-2026-0091, Date
  2026-08-28. **Against Original Tax Invoice No INV-2026-0447 dated 2026-08-20** -- the same
  invoice number referenced by `../other/india_inbound/IN-OTH-02`'s e-Way Bill, a deliberate
  cross-fixture continuity (the credit note adjusts the shipment that e-Way Bill moved).
  Reason for Credit: "Sales Return -- Item found defective on inspection." Explicit statutory
  citation: "issued under Section 34 of the CGST Act, 2017."

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1: "CREDIT NOTE" is an exact `_DOC_TYPE_SYNONYMS` entry -- classifies via the
  deterministic pass. **Confirmed against the real classifier, 2026-09-02**:
  `doc_type_method=deterministic`, `doc_type_confidence=1.0` (see `../MANIFEST.md`).
- E4/E6 MONEY family: full existing arithmetic verification applies unchanged, identical to
  how an INVOICE is checked (T-R-3's "identical alert set" reasoning extends here by
  construction, since CREDIT_NOTE shares INVOICE's schema/rubric per A2 -- CREDIT_NOTE is one
  of the four INVOICE-family types kept on `InvoiceExtractionSchema`/`_DIRECTION_PROFILES`,
  never routed to the generic profile).
- A2 relevance: this fixture is a concrete example a coder/reviewer can check
  `resolve_extraction_profile` against -- CREDIT_NOTE must stay on the INVOICE-family schema
  in both flag states, never the GENERIC profile.

## Data-quality flags

None. Internally consistent by construction (synthetic, no seeded defects). No
erroneous-CREDIT_NOTE variant or EU/US regional variant built this pass; flagged as a real
gap for the taxonomy wave, not an oversight.
