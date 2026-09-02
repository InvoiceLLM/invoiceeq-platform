# Ground Truth -- OTHER fixtures (Feature 27 Task F, Dispatch B)

Source PDFs: `../other/india_inbound/` -- 2 files, both synthetic (see `../MANIFEST.md`).
This is the **classifier's fallback-routing proof, T-C-4** (E5's scope exclusion: transport
and custody documents are deliberately out of v1 and must route cleanly to `OTHER`). Both
fixtures deliberately carry NO synonym-table match at all -- E5 states transport documents
are excluded, and `_DOC_TYPE_SYNONYMS["OTHER"]` is intentionally empty (nothing is ever a
deterministic match for OTHER) -- so both exercise the real (not mocked) LLM fallback path.
`OTHER` runs the money rubric in advisory mode only (E4): alerts recorded, never a review
status.

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Classification path |
|---|---|---|---|---|---|
| IN-OTH-01_bill_of_lading.pdf | India (export) | BILL OF LADING | OTHER | Other/advisory | LLM fallback (no deterministic match; E5 exclusion) |
| IN-OTH-02_eway_bill_quoting_tax_invoice.pdf | India | e-Way Bill | OTHER | Other/advisory | LLM fallback (no deterministic match; E5 exclusion) |

**Measured against the real classifier + real Azure OpenAI, 2026-09-02** (see
`../MANIFEST.md` for the full row): IN-OTH-01 -> `llm`, confidence 0.90, evidence "BILL OF
LADING"; IN-OTH-02 -> `llm`, confidence 0.92, evidence "e-Way Bill". Both correct, both well
above the 0.6 threshold, neither triggered the deterministic pass (verified: neither
document's title band matches any `_DOC_TYPE_SYNONYMS` phrase).

## IN-OTH-02 -- the hard case, stated explicitly

This is the fixture section 7/E5's real-world hazard actually describes: a real e-Way Bill
**quotes its own originating Tax Invoice number** in its body ("Document Details: Tax Invoice
No INV-2026-0447 dated 2026-08-20"). The classifier's title-band **coverage guard**
(`_TITLE_LINE_COVERAGE = 0.6` in `document_type_classifier.py`) is what prevents that
reference line from being read as a second, competing title -- the reference sentence covers
well under 60% of its own line's non-space characters with the phrase "tax invoice," so it
is correctly treated as a body mention, not a title. This mirrors
`tests/test_document_type_classifier.py::test_an_e_way_bill_quoting_its_tax_invoice_number_is_still_not_an_invoice`,
which uses the same shape as raw text; this fixture is the same case as an actual rendered
PDF, run through real OCR-equivalent text extraction (PyMuPDF) rather than hand-typed text.

## Header fields / body content

- IN-OTH-01 (Bill of Lading): Shipper Ashoka Precision Components Pvt Ltd. Consignee "To
  Order" (a real B/L convention -- a negotiable, unconsigned original). B/L No MAEU-4471902,
  Vessel MV Northern Star, Voyage 118W, Port of Loading Nhava Sheva, Port of Discharge
  Rotterdam, Freight PREPAID. Cargo: 2 x 40HC containers / 48 crates, "Machine Parts, Not
  Otherwise Specified," gross weight 18,400 kg. Real B/L legal boilerplate included
  ("document of title... one of three (3) originals, any one of which being accomplished the
  others to stand void") -- not a schematic placeholder.
- IN-OTH-02 (e-Way Bill): Consignor Ashoka Precision Components Pvt Ltd, GSTIN
  27AAJCA9988P1Z3. Consignee Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. EWB No 1810 0034
  5567, Generated 2026-08-20 14:22, Valid Until 2026-08-22, Mode Road, Approx Distance 412
  km, Vehicle No MH-12-CD-9987. References Tax Invoice No INV-2026-0447 dated 2026-08-20 (the
  exact invoice number reused as the Credit Note's referenced original invoice in
  `../credit_note/india_inbound/IN-CN-01`, a deliberate cross-fixture continuity). Line items
  printed with HSN codes and taxable values (an e-Way Bill legitimately carries taxable value
  for GST-transit purposes; this does not make it an invoice).

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- **T-C-4, the direct subject of this pair**: "a bill of lading and an e-way bill both
  classify OTHER." Both fixtures here are real rendered PDFs for exactly that assertion,
  complementing the raw-text unit tests already in `tests/test_document_type_classifier.py`.
- E5: neither transport document should ever reach a commercial-value rubric; `OTHER`'s
  advisory-only mode (E4) is the correct downstream handling once G5 lands.
- N2 (confidence calibration): both are real (non-mocked) LLM-path data points -- see
  `../MANIFEST.md` for the full distribution and the functional-tester recommendation on the
  0.6 threshold.

## Data-quality flags

None. Both fixtures are internally consistent by construction (synthetic, no seeded
defects). Real air-waybill or CMR-consignment-note samples were not built this pass (E5 names
bill of lading and e-way bill by name as the required T-C-4 pair; the broader transport-doc
family is explicitly out of v1 scope per E5 and is not this dispatch's budget).
