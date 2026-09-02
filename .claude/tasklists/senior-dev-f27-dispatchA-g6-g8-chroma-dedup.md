# senior-dev — F27 Dispatch A: G6 + G8 + Chroma lifecycle + ingestion dedup

Wave 1 (Step 2), Feature 27 ledger close-out. Runs parallel to the functional-tester
fixtures dispatch — no file overlap (`tests/fixtures/doc_types/**`, `MANIFEST.md`,
`test_coverage_map.md` are off-limits here).

Gap numbers: **BE Gap 384** (G6 + G8 + stale-comment fix), **BE Gap 385** (Chroma
lifecycle + ingestion dedup widening).

## Pre-flight
- [x] Read `.claude/CONVENTIONS.md` (hard rules 3, 4) and `active-work.md`.
- [x] Fresh repo-wide Gap collision check across all three trackers — highest used is
      **383** (BE 382, FE 383, website 351); 384/385 free, matching the brief.
- [x] Read F27 spec §3 E9, §10 G6/G8, §4, §2A/A4, G3b + G4 build notes.
- [x] Read the real code: `resolve_direction_profile`, `pdf_to_base64_images`,
      `chroma_client.py`, `sweep_sandbox_tenants.py`, `reembed_chroma_collections.py`,
      `routers/invoices.py::_ingest_single_file`, `services/billing_quota.py`.

## G6 — E9 fail-loud (Gap 384)
- [x] `UnknownFlowDirectionError(ValueError)` + `_VALID_FLOW_DIRECTIONS` in
      `agents/extraction_agent.py`.
- [x] `resolve_direction_profile()` raises for a non-empty unrecognised value;
      `None`/`""`/whitespace still default to INBOUND.
- [x] Validated against the three named directions, NOT `_DIRECTION_PROFILES.keys()`
      (so `"GENERIC"` raises).
- [x] Unconditional — no flag gate (E9's stated exception to E3).
- [x] Updated the now-stale comments at the `GENERIC` map entry and in
      `resolve_extraction_profile` / `resolve_verification_rubric`.
- [x] Flipped the marker test `tests/test_generic_extraction.py:435`.
- [x] Fixed 4 pre-existing tests that fed invalid directions and asserted fall-through
      (`test_generic_extraction.py` ×3, `test_chat_attachments.py` ×1) — not in the brief,
      found by running the suite.
- [x] New tests (12) — None/""/whitespace → INBOUND; `"REFERNCE"` raises; `"GENERIC"`
      raises; the three real directions unchanged; flag-OFF proof.
- [x] Narrow run green: `test_generic_extraction.py` 302 passed; `test_chat_attachments.py`
      + `test_extraction.py` + `test_trainer.py` 106 passed.
- [x] Negative control recorded: validating on `_DIRECTION_PROFILES.keys()` instead of
      `_VALID_FLOW_DIRECTIONS` → **6 failed / 296 passed**; dropping `.strip()` from the
      blank check → **3 failed / 299 passed**; restored → **302 passed**.

## G8 — image dispatch (Gap 384)
- [x] `document_to_base64_images(file_path)` with suffix dispatch (pdf / image / other).
- [x] PDF branch byte-for-byte unchanged; `download_pdf_from_storage`'s own failure path
      untouched.
- [x] Unsupported extension → `[]` **and** a WARNING naming the extension.
- [x] `pdf_to_base64_images` kept as a thin alias (outbound agent import + 1 in-file call
      site + harness docstring all still resolve).
- [x] Tests (12, incl. a parametrise over every declared suffix) incl. PNG → non-empty, WARNING asserted via caplog, PDF output identical,
      alias resolves.
- [x] Narrow run green: `test_generic_extraction.py` 321 passed; with
      `test_outbound_extraction.py` + `test_extraction.py`, 339 passed.
- [x] Negative control recorded: WARNING→DEBUG → **2 failed / 318 passed**; image
      branch disabled → **1 failed / 319 passed**; restored → **321 passed**.
- [x] **Correction of fact found here:** §4's premise that a PNG made the old function
      raise and return `[]` is stale against PyMuPDF 1.28.0 — MuPDF sniffs the real
      container and already rendered PNGs. Recorded in the docstring, in a test, and in
      the build note. G8's value is determinism + the WARNING, not new capability.
- [x] **Limitation recorded, not hidden:** `run_extraction_agent` still guards its call
      with `endswith(".pdf")`, so the image branch is unreachable from the normal
      extraction path. Widening that guard changes flag-OFF behaviour (E3) and was not
      in this dispatch's scope; a test asserts the guard so the limitation is visible.

## Resume verification (2026-09-02, after the 20-min hard stop)
- [x] Fresh Gap collision re-check: trackers still top out at **383** (BE 382, FE 383,
      website 351). 384/385 still free; the only in-repo hits for 384/385 are this
      dispatch's own already-written code/comments.
- [x] G6 + G8 re-verified intact: `test_generic_extraction.py` + `test_chat_attachments.py`
      + `test_extraction.py` + `test_trainer.py` + `test_outbound_extraction.py` →
      **437 passed**, 0 failed. No regression during the stop.

## Chroma lifecycle (Gap 385)
- [x] `chroma_client.py`: `delete_document_chunks` / `has_document_chunks` /
      `get_all_document_chunks`, all through `get_document_collection()`. Plus a fourth,
      `delete_tenant_document_collection()` — needed because per-row deletes leave an
      empty-but-present collection the orphan sweep cannot tell from a live tenant's.
- [x] `scripts/reembed_chroma_collections.py`: `docs_` added to the orphan-prune sweep via
      `ORPHAN_SWEEP_PREFIXES`. Rebuild half deliberately left invoice-only (asserted).
- [x] `scripts/sweep_sandbox_tenants.py`: `Document` rows + `docs_{tenant}` collection
      deleted on sandbox expiry (found: `Document` rows were **not** being deleted at all —
      an FK violation waiting on Postgres, not just an orphaned collection).
- [x] Tests (12, over the 10 planned): 9 in `test_documents_table.py` (lifecycle ×7,
      orphan-sweep ×2), 3 in `test_sandbox_keys.py` (reaper: rows+collection, no-documents
      no-op, unreachable-Chroma survival). Filed in `test_sandbox_keys.py` rather than
      `test_rag.py` — that is where `_purge_sandbox`'s existing coverage already lives.
- [x] Isolation re-asserted: `test_the_lifecycle_functions_cannot_reach_the_invoice_collection`
      proves `query_invoice_chunks()` still returns invoice chunks after both a
      `delete_document_chunks()` and a full `delete_tenant_document_collection()`.
- [ ] Narrow run green (`test_documents_table.py` + `test_sandbox_keys.py` + `test_rag.py`).

## Ingestion dedup widening (Gap 385)
- [x] `routers/invoices.py::_ingest_single_file` dedup widened to
      `{Invoice.file_hash WHERE tenant} ∪ {Document.file_hash WHERE tenant}`.
      `Invoice` probed first and short-circuits, so the pre-existing path is unchanged.
- [x] Tenant predicate on both sides — verified by reading the code this run
      (`Document.tenant_id == context.tenant_id` is present at `routers/invoices.py:105`).
      A prior interrupted attempt had left this predicate off the `Document` side; that
      is a cross-tenant duplicate-match/information-leak bug and the fix is applied.
- [x] Copy decision made and written into the code comment (storage pointer only;
      every extracted field left NULL; `duplicate_of_invoice_id` NULL on a document
      match, origin in the `sa_alerts` payload instead). **Not yet transcribed into a
      Gap entry or build note** — see Close-out.
- [x] Tests written: **7** in `test_ingestion.py` (one more than the 6 planned) —
      the bug itself (no re-upload, no re-queue), the field-by-field copy ruling, the
      `sa_alerts` origin pointer, invoice-match-still-wins, the cross-tenant negative
      control, soft-deleted still dedups, and ingestion-agrees-with-billing.
- [x] Narrow run green: `tests/test_ingestion.py` → **19 passed**, 0 failed (2026-09-02).
- [ ] **NOT DONE — negative control for the cross-tenant test not performed.**
      `test_another_tenants_document_is_not_a_duplicate` passes against the *fixed*
      code, but it was never run against the *unfixed* code, so it is unproven that it
      actually fails when the `Document.tenant_id` predicate is removed. Until that
      mutation is run, this test is passing-but-unvalidated and must not be cited as
      proof the isolation bug is caught. This is the single most important unfinished
      item in this dispatch.

## Chroma lifecycle — remaining
- [ ] Combined narrow run (`test_documents_table.py` + `test_sandbox_keys.py` +
      `test_rag.py`) still unconfirmed. Passed individually in an earlier run; the
      combined run has been interrupted every time it was attempted.

## Housekeeping
- [ ] **NOT STARTED.** Stale `Gap 380` comments → `Gap 382` in `agents/query_agent.py`
      (~line 3180) and `tests/test_chat_doc_content_branch.py` (~24, ~100, ~634).
      No file was touched for this. (Also still listed as a live contradiction in
      `active-work.md`.)

## Close-out
- [ ] **NOT STARTED.** Full BE suite at the dispatch boundary — never run this dispatch.
- [ ] **NOT STARTED.** Gap 384 + Gap 385 are **not filed** in `be_features_tracker.md`.
      The numbers were reserved by a collision check (highest used is still 383) but no
      entry was written. Deliberately left unfiled rather than filing an entry describing
      unverified work.
- [ ] **NOT STARTED.** G6 + G8 are **still `[ ]`** in `feature_27_generic_extraction.md`
      §10; no build note appended. Note this means the spec understates reality: G6 and
      G8 are code-complete and test-green (437 passed, confirmed twice) but their
      checkboxes do not say so. Whoever resumes should tick them, not rebuild them.
- [ ] Final self-check of §10 for other silently-already-done `[ ]` items (the G9/G10/G14
      class of drift) — not performed.

## Stop notes (2026-09-02)

Halted mid-dispatch on a founder stop instruction relayed by the coordinator. No file was
left half-written; the only edit made after the stop was to this tasklist.

Done and green: **G6** and **G8** (Gap 384's code) and the **Chroma lifecycle** +
**ingestion dedup** code (Gap 385's code). The cross-tenant tenant-predicate fix in
`routers/invoices.py` is applied and `test_ingestion.py` is **19 passed**.

Not done: the cross-tenant test's **negative control was never run**, so the isolation
fix is covered by a passing-but-unvalidated test rather than a proven one;
**Gaps 384/385 are not filed**; **G6/G8 checkboxes are not ticked** and no build note
was appended; the stale `Gap 380` → `Gap 382` comment fix was not started; the full BE
suite was not run.

**Final status: STOPPED BY FOUNDER — partial, see notes.**

---

## Resume 3 (2026-09-02) — close-out dispatch

Scope: finish the paperwork only. Negative control for the cross-tenant test,
combined Chroma narrow run, stale-comment housekeeping, full BE suite, Gap 384 +
385 filed, G6/G8 ticked, §10 self-audit. No new feature work.

- [ ] Pre-flight: CONVENTIONS + active-work + tasklist conflict re-check.
- [ ] Negative control: remove `Document.tenant_id` predicate → run the Gap 385 block.
- [ ] Restore predicate → green again.
- [ ] Combined narrow run: `test_documents_table.py` + `test_sandbox_keys.py` + `test_rag.py`.
- [ ] Housekeeping: `Gap 380` → `Gap 382` comments.
- [ ] Full BE suite.
- [ ] Fresh Gap collision re-check, then file Gap 384 + Gap 385.
- [ ] Tick G6 + G8 in F27 §10, append build note.
- [ ] §10 self-audit for silently-done `[ ]` items (report only).
