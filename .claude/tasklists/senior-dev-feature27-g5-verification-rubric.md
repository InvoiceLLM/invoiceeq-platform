# senior-dev — Feature 27 task G5: `_VerificationRubric` + `_RUBRIC_BY_DOC_TYPE` + `verify_node` gating

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_27_generic_extraction.md` §3 E6 (rubric
design), §3 E4 (the three-family table), §10 G5. Tracker: `docs/be_features_tracker.md`.

Scope: the rubric dataclass, the per-doc-type map, and gating the two arithmetic checks +
the review-status decision in `verify_node`. **Not** in scope: `run_field_confidence` /
`run_di_tax_backfill` gating (G7 — the fields exist for it to use), `invoice.coordinates`
persistence gating (G7), E9's fail-loud (G6).

- [x] Read CONVENTIONS, spec §3 E4/E6, all five build notes, `active-work.md`, tasklists (hard rule 5)
- [x] Read the real code: `verify_node`, `resolve_extraction_profile`, `DOC_TYPE_FAMILY`,
      `utils/verification_tools.py` (not modified — spec is explicit)
- [x] Collision-check the Gap number fresh immediately before writing the tracker entry —
      **376 was already claimed** by an in-flight FE dispatch (`feature_3_ingestion.md`,
      Feature 27 G11), so this work self-renumbered to **Gap 377**
- [x] `_VerificationRubric` dataclass (E6's fields + A1's two, the latter declared and unread)
- [x] `_RUBRIC_BY_FAMILY` + `_RUBRIC_BY_DOC_TYPE` derived by comprehension over `DOC_TYPES`
- [x] `resolve_verification_rubric(flow_direction, doc_type)` — `None` = "do not consult",
      three conditions (flag / INBOUND / known type); OUTBOUND + REFERENCE never reach it (A2)
- [x] `_prices_present()` — E4's quantity escalation, `is not None` never truthiness
- [x] `verify_node` gating: the two math calls + advisory-only status
- [x] Tests: T-R-1 (delivery note, no prices — `assert_not_called`), T-R-2 (contract, no
      grand total), T-R-3 (invoice: equal alerts, status, feedback AND call args),
      T-R-4 (`OTHER` advisory + PURCHASE_ORDER control), flag-OFF never consults the map
      (recording dict, not "same result")
- [x] Update the G4-era scope marker test → `test_g5s_honest_scope_...`
- [x] Run `tests/test_generic_extraction.py` → **229 passed** (144 before)
- [x] Negative controls ×3: gating removed → 3 failed; `advisory_only` removed → 3 failed;
      QUANTITY family mapped to the money rubric → 8 failed. Restored + re-run green each time.
- [x] Regression run: 363 passed (extraction-agent importers) + 118 (graph callers) +
      160 passed/1 skipped (remaining `verify_node` touchers)
- [x] Spec doc: G5 `[x]`, G7 note, additive "Build note — G5" subsection
- [x] Tracker: Gap 377 entry
- [x] Leave uncommitted

Final status: complete. G5 removes the arithmetic half of the founder's original bug; the
flag stays OFF because the DI Critic half (G7) and persistence (G9) are still open, and a
test deliberately asserts the Critic still fires as the marker for G7 to flip.
