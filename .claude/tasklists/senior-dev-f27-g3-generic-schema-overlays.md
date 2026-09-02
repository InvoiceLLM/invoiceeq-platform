# senior-dev — Feature 27, task G3 (generic schema + overlays + prompt builders)

Scope: `feature_27_generic_extraction.md` §10 **G3 only** — `GenericLineItem`,
`GenericDocumentSchema`, `_DOC_TYPE_OVERLAYS`, `build_generic_multimodal_prompt()` /
`_build_generic_text_prompt()`, all **additive** in `agents/extraction_agent.py`.

**Not** in scope, per dispatch: G3b (`resolve_extraction_profile` + the `GENERIC` profile
entry), G4 (`classify_doc_type_node`, graph entry point), G5 (`_VerificationRubric`),
G7 (`queue_worker/handlers.py`). `ReferenceDocExtractionSchema`, `InvoiceExtractionSchema`,
`OutboundInvoiceExtractionSchema` and `_DIRECTION_PROFILES` stay byte-for-byte as they are.

- [x] Read `.claude/CONVENTIONS.md`, `active-work.md`, `feature_27_generic_extraction.md`
      (esp. E4's taxonomy, E8, A2, and the G1/G2 build note's two carried decisions)
- [x] Hard rule 5 — in-flight check: tasklists from the last 7 days grepped for
      `extraction_agent` / `feature_27` / `generic`. The only live threads touching this
      file's *subject* are Feature 26 Part 2 (H1/H2 — `utils/llm.py`, `chroma_client.py`,
      `scripts/`) and F27 task F (fixtures on disk). `agents/extraction_agent.py` was
      unmodified in `git status` at start. No conflict.
- [x] Read `services/document_type_classifier.py` (what G2 actually exports) and
      `agents/extraction_agent.py`'s reference schema + reference prompt builders
- [x] `GenericLineItem` — every field Optional/None, no coercion of absence to 0
- [x] `GenericDocumentSchema` — E8's union spine, in E8's order
- [x] `_DOC_TYPE_OVERLAYS` (9 entries, one per non-INVOICE `doc_type`) +
      `_GENERIC_FAMILY_STANCE` + `resolve_doc_type_overlay()`. Family constants compared
      against by name, never the literal `"INVOICE"`. `QUOTATION` kept on `COMMITMENT`.
- [x] `build_generic_multimodal_prompt()` / `_build_generic_text_prompt()`
- [x] Tests — `tests/test_generic_extraction.py` (schema/overlay/prompt-builder slice)
- [x] Run the tests → **53 passed in 9.10s**. Negative control (GRN overlay deleted +
      `unit_price` defaulted to `0.0`) → exactly 7 failed, 46 green; restored, re-run green.
      Regression: 187 passed across every suite importing `extraction_agent`; 37 passed on
      `test_chat_attachments.py` + `test_sse.py`.
- [x] Spec doc: G3 `[x]` + "Build note — G3, 2026-09-02" (additive, hard rule 4)
- [x] Tracker Gap entry — collision-checked immediately before writing: max was **370**
      (369 at dispatch; Gap 370 filed concurrently by the F26 P2 thread), filed as **Gap 371**
- [x] Leave uncommitted

**Final status (2026-09-02): complete.** G3 built additively (430 insertions, 0 deletions in
`agents/extraction_agent.py`), 53 new tests passing, spec + tracker updated. Nothing calls
the new code — G3b/G4/G5/G7 are the wiring. Two decisions carried from Gap 369 remain open
and were not settled here: the `MONEY` vs `"INVOICE"` family name (G3 uses the exported
constants and takes no position), and `QUOTATION`'s provisional `COMMITMENT` mapping
(honoured; its overlay reads correctly under either family).
