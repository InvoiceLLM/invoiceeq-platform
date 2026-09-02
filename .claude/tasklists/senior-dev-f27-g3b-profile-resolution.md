# Feature 27 — G3b: `resolve_extraction_profile()` + the `GENERIC` profile entry

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_27_generic_extraction.md` §2A/A2
("Profile resolution — the exact rule to implement"), §10 G3b.
Continues G1/G2 (Gap 369) and G3 (Gap 371). Additive; called from nowhere (G4 wires it).

- [x] Read CONVENTIONS.md, the spec (§2A/A2, §4, §10 + all three build notes)
- [x] Check in-flight work (`.claude/tasklists/`, hard rule 5) — G3's tasklist is this task's
      direct predecessor, no conflict; F26 Part 2 H2 touched `chroma_client.py` only
- [x] Read the real code: `_DirectionProfile`, `_DIRECTION_PROFILES`,
      `resolve_direction_profile`, G3's generic schema/overlays/builders,
      `services/document_type_classifier.py`'s exported family constants
- [x] Confirm the flag-read pattern actually used in this repo (`get_settings().ENABLE_*`,
      `config.settings` monkeypatched in tests) rather than assuming one
- [x] Confirm `_DIRECTION_PROFILES["REFERENCE"]` really uses `EXTRACTED`/`EXTRACT_FAILED`
      before copying that pair (it does — L973-974)
- [x] Collision-check the Gap number fresh immediately before writing (max filed = 371 → 372)
- [x] Add the `GENERIC` entry to `_DIRECTION_PROFILES` — schema/builders/`required_fields=()`
      /`EXTRACTED`+`EXTRACT_FAILED`/`legacy_audit_path_shim=False`, `max_tokens=8192`
      (REFERENCE's figure, recorded as a starting value not a measured one)
- [x] Add `resolve_extraction_profile(flow_direction, doc_type)` — A2's four conditions,
      `MONEY_FAMILY` constant not the `"INVOICE"` literal, fail-closed on every
      fall-through incl. an out-of-vocabulary doc_type (logged, not raised)
- [x] Extend `tests/test_generic_extraction.py` with the four-condition truth table
      (all four true → GENERIC; each false in turn → identical to
      `resolve_direction_profile`), OUTBOUND/REFERENCE unaffected for every `DOC_TYPES`
      value, and the two G3 scope tests updated for what now exists
- [x] Run the tests — **120 passed in 6.68s** (53 before this change)
- [x] Negative control ×2 — `family == "INVOICE"` → exactly 8 failures / 112 green;
      flag check + direction check deleted → 23 failures / 97 green; restored after each,
      re-run → 120 passed
- [x] Regression sweep — extraction_agent importers → **254 passed**;
      `test_chat_attachments.py` + `test_sse.py` → **37 passed**
- [x] File Gap 372 in `be_features_tracker.md` (max was 371 at write time, re-checked)
- [x] Update the spec: G3b `[x]` + additive "Build note — G3b, 2026-09-02" subsection
- [x] Leave everything uncommitted (`git diff --numstat` on `agents/extraction_agent.py`:
      **590 insertions, 0 deletions** vs HEAD for G3+G3b together)

**Final status: complete.** The function is correct in isolation and called from nowhere —
`extract_node`/`verify_node`/`run_extraction_agent` still call `resolve_direction_profile`,
asserted by a source-reading test. Evidence caveat: pure Python, mocked LLM, no Postgres;
T-OFF-1/T-R-6 are not attempted and remain task V, blocked on §7 task F's fixtures.
