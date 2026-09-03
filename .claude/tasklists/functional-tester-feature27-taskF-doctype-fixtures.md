# functional-tester -- Feature 27 Task F: doc-type fixture sourcing (1-hour slice)

Scope: feature_27_generic_extraction.md section 7. Full task is 1-2 days per the spec own
estimate; this file tracks a single time-boxed 1-hour slice, not the whole task.

- [x] Read feature_27_generic_extraction.md in full (all of section 1 through section 11,
      including A1-A4 amendments and E1-E10 decisions) plus E4 taxonomy synonym table.
- [x] Read active-work.md and scanned .claude/tasklists/ for in-flight conflicts -- none
      found referencing feature_27, document_type_classifier, or task F.
- [x] Confirmed services/document_type_classifier.py does not exist yet (G2 not started) --
      consuming-test code correctly out of scope for this dispatch.
- [x] Read precedent structure: tests/india/inbound/, tests/eu/inbound/ (6 graded PDFs each)
      plus tests/india/ground_truth_line_items.md, tests/eu/ground_truth_line_items.md.
- [x] Created tests/fixtures/doc_types/ directory tree (delivery_note/, proforma_invoice/,
      each with india_inbound/eu_inbound/us_inbound subfolders as applicable).
- [x] Wrote tests/fixtures/doc_types/_generate_fixtures.py (standalone reportlab generator,
      does not reuse tests/e2e/pdf_builder.py since that hardcodes an INVOICE title).
- [x] Generated 5 synthetic PDFs: IN-DN-01 (India delivery challan, no prices), EU-DN-01
      (Germany Lieferschein, no prices), IN-PI-01/EU-PI-01/US-PI-01 (India/EU/US proforma
      invoice, all three regions per section 7 table).
- [x] Sanity-checked rendered text of 2 PDFs via PyMuPDF extraction -- title bands render
      correctly (DELIVERY CHALLAN, PROFORMA INVOICE).
- [x] Wrote tests/fixtures/doc_types/MANIFEST.md -- per-file doc_type/family/region/
      real-or-synthetic/provenance/expected-evidence-phrase, plus an explicit
      "NOT YET SOURCED" table for every other section 7 cell (QUOTATION, PURCHASE_ORDER,
      CONTRACT, GRN, CREDIT_NOTE, DEBIT_NOTE, OTHER -- all 0 percent covered).
- [x] Wrote ground_truth_line_items.md-style files for both covered types:
      tests/fixtures/doc_types/delivery_note/ground_truth_line_items.md and
      tests/fixtures/doc_types/proforma_invoice/ground_truth_line_items.md.
- [x] Updated apps/invoice-be/docs/test_coverage_map.md with an honest IN PROGRESS entry
      (not a completion claim).
- [x] Left everything uncommitted per standing instruction.

Final status: 1-hour slice complete. 5 of ~30-40 target fixture files produced, covering
2 of 10 section 7 doc types (DELIVERY_NOTE 2/3 regions, PROFORMA_INVOICE 3/3 regions).
7 doc types (QUOTATION, PURCHASE_ORDER, CONTRACT, GRN, CREDIT_NOTE, DEBIT_NOTE, OTHER) have
zero fixtures and are explicitly marked NOT YET SOURCED in MANIFEST.md for the next session.
No consuming test code written (out of scope per dispatch instructions -- classifier module
G2 does not exist yet).
