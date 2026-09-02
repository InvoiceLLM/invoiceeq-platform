# senior-dev — Feature 27, tasks G1 + G2 (flag + document-type classifier module)

Scope: `feature_27_generic_extraction.md` §10 G1 and G2 only. Standalone module +
config flag. **Not** wired into the extraction graph (G3/G3b/G4 are a later dispatch).
Files out of scope and not to be touched: `agents/extraction_agent.py`,
`queue_worker/handlers.py`, `models.py`, `chroma_client.py`, `services/billing_quota.py`.

- [x] Read `.claude/CONVENTIONS.md`, `active-work.md`, full `feature_27_generic_extraction.md`
- [x] Hard rule 5 — in-flight check: tasklists modified in last 7 days grepped for
      `document_type_classifier` / `ENABLE_GENERIC_EXTRACTION` / `feature_27` → zero hits.
      The two live senior-dev threads (Track B chat progress, F23 3-way model comparison)
      touch `routers/chat.py` / benchmarks, not this feature's files. No conflict.
- [x] Verify current line numbers of `ENABLE_ASYNC_CHAT_QUEUE` (L61) /
      `ENABLE_PRODUCTION_QUALITY_JUDGE` (L311) — both confirmed at the cited lines
- [x] G1 — `config.py`: `ENABLE_GENERIC_EXTRACTION: bool = False` + house-style docstring
      incl. the explicit software-level-not-per-tenant statement (E1, E2)
- [x] G2 — `services/document_type_classifier.py`: `DOC_TYPES`, `DOC_TYPE_FAMILY`,
      `_DOC_TYPE_SYNONYMS`, `classify_doc_type_deterministic()`, `DocTypeClassification`,
      `classify_doc_type()`
- [x] Tests — `tests/test_document_type_classifier.py`, T-C-1 … T-C-4
- [x] Run `python -m pytest tests/test_document_type_classifier.py -v` and report the real result
      → **88 passed in 7.30s** (2026-09-02), incl. 2 negative controls run by hand
- [x] Spec doc §10 G1/G2 marked done + a "Build note" recording the two deviations
      (family name `MONEY` vs A1/A2's `"INVOICE"`; `QUOTATION` unassigned by E4)
- [x] Tracker Gap entry, number collision-checked fresh immediately before writing
      → repo-wide max was 367, filed as **Gap 368**
- [x] Leave uncommitted

**Final status (2026-09-02): complete.** G1 + G2 built, 88 tests passing, spec + tracker
updated. Two open decisions deliberately left for the founder rather than silently settled
— see the spec's "Build note (G1/G2)" and Gap 368: (1) `DOC_TYPE_FAMILY`'s money-family key
is `MONEY`, but A1/A2 compare against `"INVOICE"` — G3b/G5 must use one name; (2) E4's
family table never assigns `QUOTATION`, provisionally mapped to `COMMITMENT`.
