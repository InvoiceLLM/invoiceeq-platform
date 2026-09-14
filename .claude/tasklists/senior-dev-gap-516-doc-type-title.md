# BE Gap 516 — STATEMENT_OF_ACCOUNT overload + the bank-statement title miss

- [x] Read CONVENTIONS, gap-work / done / verify-postgres skills, the Gap 516 entry
- [x] Check whether Feature 27's ledger has closed (active-work.md "Frozen / do not touch",
      F27 §10A) — **it has NOT**: task V `[ ]`, R-27-26 migration "never applied".
      Half 1 (the BANK_STATEMENT split) therefore NOT attempted, per the task's own condition.
- [x] Half 2: state the defect class + call-site count (1 found / 1 fixed)
- [x] Implement the mechanism fix in `services/document_type_classifier.py`
      (`_TITLE_SEGMENT_SEPARATORS`, `_REFERENCE_QUALIFIER_TOKENS`,
      `_title_segment_doc_types()`, `_resolve_title_line()`) — no synonym added
- [x] Prove against the real `classify_doc_type_deterministic()` incl. mutated fixtures
- [x] Registry-driven property tests in `tests/test_document_type_classifier.py`
- [x] Verify on real Postgres: 260 / 504+2s / 183 / 4 passed
- [x] Spec bodies: `feature_27_generic_extraction.md` (G1/G2 build note item 1),
      `feature_30_business_intelligence.md` §12.8 + §12.7
- [x] Tracker: Gap 516 `[ ]` -> `[~]` with evidence verbatim; Feature 30 line corrected
- [x] Nothing committed

**Final status:** 516.2 fixed and verified; 516.1 blocked on the frozen taxonomy — founder call.
