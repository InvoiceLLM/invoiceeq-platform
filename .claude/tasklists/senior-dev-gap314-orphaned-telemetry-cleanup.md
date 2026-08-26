# Gap 314 — delete orphaned Ops Digest telemetry, 2026-08-26

Feature 24 was deleted by Gap 311 (2026-08-25, `f985ee9`), 10 artifacts removed. Two were missed:
`OPS_DIGEST_EVENT_NAME` and `track_ops_digest_run()` in `Prod_Invoice_LLM/apps/invoice-be/telemetry.py`.
This task deletes them. Code deletion is the point of the gap; hard rule 4 (never delete approved specs)
constrains only the tracker/spec markdown, which stays additive.

Files: `apps/invoice-be/telemetry.py`, `apps/invoice-be/tests/test_telemetry.py`,
`apps/invoice-be/agents/sage_prompts.py` (one stale cross-reference),
`apps/invoice-be/docs/be_features_tracker.md`, `apps/invoice-be/docs/feature_20_23_24_ops_workbook.md`.

- [x] 0. Read CONVENTIONS.md + `active-work.md`; checked `.claude/tasklists/` — the only same-file recent run
      (`senior-dev-gap-doc-reconciliation-2026-08-26.md`, both docs) is closed with a DONE final status, so no
      parallel work. `active-work.md` "F24 Ops Digest — deleted; do not rebuild" is consistent with deleting, not
      rebuilding, this residue
- [x] 1. Fresh repo-wide grep, `.py`/`.json`/`.kql`/`.bicep`/`.ps1`/`.yml`/`.yaml`/`.ts`/`.tsx` across all of
      `Prod_Invoice_LLM/`, for `track_ops_digest_run` / `OPS_DIGEST_EVENT_NAME` / `ops_digest_run` — outside
      `telemetry.py` itself: **exactly 1 hit**, and it is a *docstring* in `tests/test_telemetry.py` naming
      `ops_digest_run` as a peer event, not a call. **Zero callers, zero tests confirmed.** The `.json`/`.kql` half
      matters independently: no workbook panel or saved query reads the event name
- [x] 2. `__all__` / export list in `telemetry.py` — **none exists** (grep: no matches), nothing to update
- [x] 3. Deleted `OPS_DIGEST_EVENT_NAME` + its 10-line Feature 24 rationale comment (was line 154); left a short
      tombstone comment naming Gap 311/314, matching `config.py`/`.env.example`'s existing `OPS_DIGEST_*` notes
- [x] 4. Deleted `track_ops_digest_run()` in full — signature, docstring, body, 52 lines (was 1255–1306).
      Checked `_STATUS_ERROR`/`_STATUS_SUCCESS` are still used by 5 other emitters — left alone
- [x] 5. Two surviving docstring references to the now-dead event corrected to "(and the deleted `ops_digest_run`)":
      `telemetry.py::track_ops_recommendation` and `tests/test_telemetry.py::test_no_tenant_or_request_id_...`
- [x] 6. `agents/sage_prompts.py` module docstring cited Gap 314 as precedent for *flagging* an orphan rather than
      deleting it — corrected to record that Gap 314 went on to delete, with the distinction that keeps its own
      five orphans alive (no plausible future use → delete; open founder question → keep)
- [x] 7. `pytest tests/test_telemetry.py` → **60 passed** in 36.75s. Affected file only, per the standing rule
- [x] 8. `ruff check telemetry.py tests/test_telemetry.py agents/sage_prompts.py` → **All checks passed!**
      Plus `ast.parse` on all three, to prove the two excisions left no broken syntax
- [x] 9. Tracker Gap 314 `[ ]` → `[x]` + a `**Fixed 2026-08-26**` block (what was deleted with line numbers, the
      grep result incl. the no-workbook-reads-it finding, the 60-passed run, the ruff result, what was *not*
      touched). Original entry body carried forward **verbatim** — verified programmatically against `HEAD`
- [x] 10. Spec `feature_20_23_24_ops_workbook.md`: its "The digest build, superseded" section lists Gap 311's
      deletions and did **not** mention these two, so an `**Addendum 2026-08-26 (Gap 314)**` was added completing
      that list, with the doc-relevant fact (no panel read the event; it never held a row, since
      `caj-ops-digest-dev` was never deployed — so it belongs in no empty-panels table). Purely additive
- [x] 11. Final status here; summary reported in chat

Final status: **DONE.** Both orphans deleted, zero callers re-confirmed by fresh grep before deleting, no test
existed for either (none deleted), no `__all__` to update. 3 stale prose references corrected rather than left
pointing at a deleted symbol. `pytest tests/test_telemetry.py` 60 passed; `ruff check` clean on all 3 touched code
files. Tracker + spec updated additively — 1 tracker line replaced, its original text carried forward verbatim and
verified against `HEAD` by script; everything else new. Changes left uncommitted.
