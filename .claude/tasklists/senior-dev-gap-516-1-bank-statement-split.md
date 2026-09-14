# BE Gap 516.1 — split BANK_STATEMENT out of STATEMENT_OF_ACCOUNT

Founder unfroze the doc-type taxonomy 2026-09-14 for this one value only.

- [x] Record the unfreeze in `active-work.md` § "Frozen / do not touch" (additive, original text kept)
- [x] `services/document_type_classifier.py`: `DOC_TYPES`, `DOC_TYPE_FAMILY`, `_DOC_TYPE_SYNONYMS`, LLM prompt disambiguation rule
- [x] `agents/extraction_agent.py`: doc-type overlay for BANK_STATEMENT
- [x] `agents/query_agent.py`: `_ADVISORY_DOC_TYPES`, `_INTENT_BIAS_BY_DOC_TYPE`, `_DOC_TYPE_PHRASES`, deictic pattern
- [x] `services/attachment_extraction.py`: `land_statement_lines()` runs for BANK_STATEMENT only
- [x] `services/attachment_insights.py`: `INSIGHT_DOC_TYPES`, `DOC_TYPE_LABELS`, `CARDS_BY_DOC_TYPE`
- [x] `services/certified_examples.py`, `services/document_comparison.py`, `knowledge/rule_cards/us/us-supporting-documents.md`
- [x] `benchmarks/insight_golden.json` — the two bank cases retyped
- [x] Fixture + MANIFEST for the new type (the A-series coverage gate demands one per type)
- [x] Property tests (bank statement by its own name → BANK_STATEMENT; supplier "Statement of Account — <vendor>" → STATEMENT_OF_ACCOUNT and NOT landed as bank lines; mutated banks/vendors)
- [x] DB: check whether any enum/check constraint carries doc_type (add-only migration if so)
- [x] Verify on real Postgres — named files, then the full suite once
- [x] Tracker Gap 516 + `feature_30_business_intelligence.md` + `feature_27_generic_extraction.md`
- [x] Nothing committed

**Final status 2026-09-14:** Gap 516.1 built, verified and closed; Gap 516 now `[x]` in full.
No migration was needed (`doc_type` is varchar(32), no check constraint, no PG enum — checked
against the live DB). No FE file was touched. Full BE suite **4039 passed, 4 skipped,
5 deselected in 206.72s**. Nothing committed.

**Open for the founder:** a bank statement titled only "Statement of Account" / "Kontoauszug"
(including the showcase demo's own HDFC file) is typed by the LLM stage, not deterministically —
those phrases are shared with the supplier document and were left out of the bank entry by the
founder's own ambiguity rule.
