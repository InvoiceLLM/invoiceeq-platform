# senior-dev — Feature 27 task G7: DI trust boundaries (tracker Gap 379)

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_27_generic_extraction.md` §2A/A1
(the "What replaces G7" table), §8 trap 1, §10 G7.

**Honest note on this file:** written partway through the run rather than before it
started, contrary to CONVENTIONS §"Live task list". Recorded rather than backdated.

- [x] Read CONVENTIONS, `active-work.md`, the full spec incl. all five prior build notes
      (G1/G2, G3, G3b, G4, G5) and §8's current trap numbering (the DI-fields trap is
      still numbered **1**, replacing the void `prebuilt-layout` dict-shape trap).
- [x] Check `.claude/tasklists/` for in-flight overlap — several parallel Feature 26/27
      dispatches are live; none touches these three call sites.
- [x] Re-verify the real call sites rather than the spec's line numbers:
      `verify_field_confidence` at `extraction_agent.py` check 8 in `verify_node`; the
      Gap 68 backfill at the tail of `extract_node`; `invoice.coordinates` at the single
      persistence assignment in `queue_worker/handlers.py`.
- [x] Gate 1 — Critic step on `rubric is None or rubric.run_field_confidence`, reusing
      G5's already-resolved `rubric` local. Threshold override left resolved outside.
- [x] Gate 2 — Gap 68 backfill on `run_di_tax_backfill`, resolving through G5's
      `resolve_verification_rubric` (imported and called, family lookup not re-derived).
- [x] Gate 3 — `_should_persist_coordinates(doc_type)` in `queue_worker/handlers.py`;
      money family → DI boxes kept, everything else → `[]`, `None`/unknown → today's
      behaviour.
- [x] Enabler for gate 3: `run_extraction_agent` returns `doc_type` (only that key).
      Deviation from G4's "defer to G9" — recorded in the build note and the tracker.
- [x] Docstring-only fix to `agents/outbound_extraction_agent.py`, which claimed the
      three-key return shape.
- [x] Tests — 44 added to `tests/test_generic_extraction.py`, incl. T-R-7 parametrised
      over every non-money type, T-R-3 re-confirmed with the Critic gate layered on, the
      backfill table, and three tests through the real `handle_process_invoice`.
      Two G5-era marker tests flipped, not deleted.
- [x] Negative controls ×3 (Critic gate removed → 8 fail; backfill gate removed → 6 fail;
      `"INVOICE"` literal instead of `MONEY_FAMILY` → 7 fail), sources restored each time.
- [x] Regression sweep: 407 / 118 / 160+1skip, plus the `queue_worker`-referencing suites
      (168 passed, 1 pre-existing-looking `test_connectors.py` Postgres failure, reported
      rather than dismissed).
- [x] Gap number collision-checked fresh immediately before writing → repo-wide max 378
      (claimed twice, BE H5 + FE G11 — a pre-existing collision, recorded not resolved),
      so this is **379**.
- [x] Tracker entry (Gap 379) + spec `[x]` G7 + additive "Build note — G7" subsection.

**Final status: complete, 2026-09-02.** 273 passing in `tests/test_generic_extraction.py`.
Both halves of the founder's original bug (G5's arithmetic + G7's DI checks) are now fixed;
the flag is safe to turn **on for testing**, and still must not be turned on in a
user-facing deployment until G9 (persistence/`documents` table) and G11+G14 land.
Everything left uncommitted.
