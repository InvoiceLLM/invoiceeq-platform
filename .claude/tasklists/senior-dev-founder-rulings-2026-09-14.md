# Three founder rulings, 2026-09-14 (BE)

## 1. Feature 28 — "Reword the row"
- [x] `docs/feature_28_image_upload_pdf_boundary.md` §6 Manual/Azure row: drop the highlight-alignment clause, add dated founder-ruling note
- [x] Same doc §"results" row (line ~102): restate as PASS under the reworded wording
- [x] `docs/be_features_tracker.md` line ~72: Feature 28 `[~]` -> `[x]` + dated bullet citing `docs/test_evidence/f28_image_upload_2026-09-14/README.md`
- [x] done-gate applied and recorded

## 2. Gap 516 — "Rename the demo file title"
- [x] `showcase/vpi_demo/make_financial_docs.py::bank_statement()` title -> "HDFC BANK LIMITED — BANK STATEMENT"
- [x] Regenerate ONLY `BankStatement_HDFC_4471_Aug2026.pdf`
- [x] Prove with real `classify_doc_type_deterministic()` -> BANK_STATEMENT
- [x] `showcase/vpi_demo/README.md` scenario 10 note rewritten
- [x] Gap 516 tracker entry: dated bullet, ruling recorded, supplier-statement vocabulary untouched

## 3. Feature 30 task 30.9 — "Drop the India cards"
- [x] Delete `knowledge/rule_cards/in/` (3 unverified skeletons)
- [x] `knowledge/rule_cards/README.md`: India section replaced with the drop ruling
- [x] `tests/test_rule_cards.py`: region set, the India-count test, the unverified-display test
- [x] `docs/feature_30_business_intelligence.md`: 30.9 marked dropped, reason = no reachable primary source
- [x] `docs/be_features_tracker.md` line 52: 30.9 closed as dropped; marker decision

## Verification (real Postgres 5433)
- [x] `tests/test_rule_cards.py tests/test_insight_track_b.py`
- [x] `tests/test_document_type_classifier.py`
- [x] `tests/test_no_hardcoding.py`

Status: COMPLETE 2026-09-14. All three rulings applied, docs + code updated, uncommitted.
Verified on real Postgres (5433): test_rule_cards + test_insight_track_b `57 passed in 11.75s`;
test_document_type_classifier `336 passed in 7.99s`; test_no_hardcoding `4 passed in 13.81s`.
Markers: Feature 28 `[~]` -> `[x]`; Feature 30 `[~]` -> `[x]`; Gap 516 already `[x]`, dated bullet added.
