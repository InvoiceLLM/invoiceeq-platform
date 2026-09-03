# functional-tester -- Feature 27 Dispatch B: Task F fixture coverage (2/10 -> 10/10)

Scope: feature_27_generic_extraction.md section 7 (fixture set) and section 11.
Only touches tests/fixtures/doc_types/**, MANIFEST.md, test_coverage_map.md.
No .py application code, agents/, chroma_client.py, routers/, scripts/ touched.
Parallel senior-dev dispatch (G6/G8/Chroma lifecycle) has zero file overlap by design.

- [x] Read CONVENTIONS.md, active-work.md -- confirmed no in-flight tasklist
      conflicts with tests/fixtures/doc_types/ (predecessor slice from earlier
      session is stale: classifier module didn't exist then, it does now per
      Gap 369 / G2 landed).
- [x] Read feature_27_generic_extraction.md section 7 (fixture requirements),
      section 9 (verification plan, T-C-*, T-R-*), section 2A/N2 (confidence
      threshold calibration ask).
- [x] Read existing _generate_fixtures.py, MANIFEST.md, both existing
      ground_truth_line_items.md files, services/document_type_classifier.py
      (full), tests/test_document_type_classifier.py (full).
- [x] Confirmed real Azure OpenAI credentials present in .env; confirmed
      .venv/Scripts/python.exe has reportlab + PyMuPDF available.
- [x] Extended _generate_fixtures.py with 11 new gen_* functions:
      PURCHASE_ORDER (India, US), CONTRACT (India "RATE CONTRACT" no total,
      EU "RAHMENVERTRAG" no total), QUOTATION (India), GRN (India),
      OTHER (bill of lading + e-way-bill quoting a tax invoice), CREDIT_NOTE
      (India), DEBIT_NOTE (India), DELIVERY_NOTE US "PACKING SLIP".
- [x] Ran generator -- 16 PDFs total (5 pre-existing regenerated + 11 new)
      written under tests/fixtures/doc_types/<type>/<region>/.
- [x] Wrote/extended ground_truth_line_items.md for all 8 new/changed type
      directories (purchase_order, contract, quotation, grn, other,
      credit_note, debit_note, delivery_note).
- [x] Wrote scratch measurement script (NOT committed) that extracts each
      fixture's text via PyMuPDF and runs the real classify_doc_type() over
      all 16 fixtures. Ran it: 16/16 correct, 13 deterministic (1.0
      confidence), 3 real LLM-fallback calls (0.90/0.92/0.95 confidence)
      against the live deployed Azure OpenAI gpt-5-mini.
- [x] Rewrote MANIFEST.md: corrected the stale "classifier does not exist
      yet" claim, added the classifier-confidence column for all 16 files,
      updated coverage table to 10/10, added the threshold recommendation.
- [x] Appended a dated entry to apps/invoice-be/docs/test_coverage_map.md.
- [x] Reported to chat: before/after counts, full confidence distribution,
      explicit recommendation on the 0.6 threshold (raise to ~0.75-0.8,
      directional not final).

Final status: COMPLETE. 10/10 section-7 doc types now have at least one
fixture (16 files total, up from 5). All 16 classify correctly against the
real, shipped classifier. Full regional matrix, erroneous variants and
pipeline-level verification (task V) remain out of this dispatch's scope,
stated explicitly in MANIFEST.md and test_coverage_map.md.
