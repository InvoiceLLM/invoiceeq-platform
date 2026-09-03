# senior-dev — Wave 0: F27 / F26 Part 2 documentation reconciliation

Documentation-only pass. No application code, no infra, no test files.
Runs alone — no other dispatch may touch these files concurrently
(a prior Gap-number collision happened exactly this way).

## A. Pre-flight
- [x] 1. Read `.claude/CONVENTIONS.md` (hard rule 4 governs every spec edit)
- [x] 2. Read `active-work.md` — note: it says "Agents never edit this file", which
      conflicts with steps 24-28 of this dispatch. Flagged in the final report.
- [x] 3. Fresh repo-wide Gap collision check across all three trackers **and every
      `feature_N_*.md`**: max in use = **380** (FE, H11). Next free = 381.
      Matches the dispatch's expectation. **BE 381, BE 382, FE 383.**
- [x] 4. Read the three tasklists being closed

## B. BE Gap 381 — F27 G9/G10/G14
- [x] 5. Verified what landed: `models.py` (`Document`, `Invoice.doc_type`),
      migration `e4f5a6b7c8d9` (down_rev `d3e4f5a6b7c8`, NOT §4's cited
      `c2d3e4f5a6b7`), `chroma_client.py` (`_document_collection_name`,
      `get_document_collection` DOES pass `_collection_metadata()`),
      handlers.py (`tenant_id` from the loaded row, delete by id+tenant_id),
      billing_quota union (tenant predicate on BOTH sides — confirmed),
      `routers/documents.py` (404 not 403) registered in `main.py` L181.
- [x] 6. `tests/test_documents_table.py` exists — 21 tests, all of T-E10-1..5,
      Postgres-gated via `pg_engine_or_skip()` (skips, never falls back).
      **No recorded run anywhere; migration never applied to Postgres.**
- [x] 7. `routers/invoices.py` **unmodified** — A4/F5's required ruling was made
      neither in code nor in prose. Open item.
- [x] 8. Gap 381 written in `be_features_tracker.md`
- [x] 9. Five open items recorded in the entry (A4/F5, Chroma lifecycle, no
      sweep, no FE surface, invisible to chat)

## C. BE Gap 382 — F26 H5 missing feature flag
- [x] 10. `ENABLE_GENERIC_DOC_CHAT: bool = False` at `config.py` L256; gate at
      `query_agent.py` L3198 — flag OFF genuinely skips
      `_classify_attachment_intent()` (verified, not an unreachable branch)
- [x] 11. Flag-OFF parity tests DO exist (6, in `test_chat_doc_content_branch.py`).
      No recorded run. **Found: the flag code + tests cite "Gap 380", which is
      FE Gap 380 (H11). Left unfixed — doc-only pass.**
- [x] 12. Gap 382 written, cross-referencing BE Gap 378

## D. FE Gap 383 — F26 H12
- [x] 13. Steps 5-9 all landed (XHR upload + state machine + cancel/abort/remove,
      `attachment_id` on send with the confirmation/clarification exception,
      `confirmMatches`, reload via `GET /chat/attachments/{id}`, 5 props on
      page.tsx). Reload **is** client-side reconstruction (sessionStorage memo +
      transcript scan) because there is no list-for-session endpoint and no
      `attachment_id` column — recorded as H12's own deviation.
      **Found still open: `confirmMatches` has no consumer — `ChatWindow` L722
      renders `<MessageStream>` with no `attachmentHandlers`.**
      Step 10 done (new spec + H10's "stays dark" test inverted); step 11 has no
      recorded result.
- [x] 14. All three proxy routes confirmed under `app/api/chat/`
- [x] 15. Gap 383 written; H11's `MessageResponse`/`ChatMessage` blocker carried
      forward as an explicit open BE-side item

## E. Spec checkbox + build-note updates (ADDITIVE ONLY)
- [x] 16. feature_27: G9/G10/G14 → `[x]` + "Built 2026-09-02 (Gap 381)" pointers
- [x] 17. feature_27: "Build note — G9/G10/G14, 2026-09-02 (tracker Gap 381)"
      inserted between G7's and G11's build notes
- [x] 18. feature_27: additive rollout-status update in G11's block (half the
      §2A/N1 gate closed); **G11's `[~]` untouched**
- [x] 19. feature_26: H12 → `[x]` + "Done 2026-09-02, Gap 383 (FE tracker)"
- [x] 20. feature_26: two additive "Correction — BE Gap 382" subsections, one
      beside E-1's H5 build note and one beside E-3's. Nothing rewritten.

## F. Gap 378 collision
- [x] 21. Disambiguation sub-bullets added to BE Gap 378 and FE Gap 378.
      Neither renumbered.
- [x] 22. Numbering rule + fresh-check discipline recorded under "Open Items /
      Gaps" in `be_features_tracker.md` (CONVENTIONS.md was out of scope for
      this dispatch's allowed-files list).

## G. Stale tasklist closure
- [x] 23. All three closed with real final-status lines; unticked items left
      unticked (test runs on all three, the A4/F5 ruling, the
      `attachmentHandlers` thread). No file deleted.

## H. active-work.md refresh
- [x] 24. `_Last updated:_` → 2026-09-02
- [x] 25. Current direction: F27 + F26 Part 2 active, both flag-gated off, neither
      safe to enable; plus an honest note that "built" ≠ "verified" for both
- [x] 26. In flight: F23 3-way marked closed-2026-09-01 (verified stale);
      arch-docs Gap 244 confirmed still stale/unresolved; F27 and F26 Part 2
      open items added
- [x] 27. Frozen: no taxonomy/schema amendment work until F27's ledger closes and
      its flag-safety equality test passes against real Postgres
- [x] 28. Open contradictions: BE/FE Gap 378 (resolved-by-disambiguation, not
      re-opened) + the unfiled `MessageResponse`/`ChatMessage` plumbing gap

## I. Close-out
- [x] 29. No test run (doc-only). **No `.py`/`.ts` file was touched.** Two things
      that would have needed code edits were reported instead, not done:
      the A4/F5 dedup ruling, and the stale "Gap 380" comments in
      `query_agent.py` + `test_chat_doc_content_branch.py`.
- [x] 31. Reported: Gap numbers used (BE 381, BE 382, FE 383 — matching the
      dispatch's expectation), collision check confirmed max 380, and every open
      item surfaced.

Final status: **complete, 2026-09-02.** Documentation-only. Gap numbers used:
**BE 381** (F27 G9/G10/G14), **BE 382** (F26 H5's missing `ENABLE_GENERIC_DOC_CHAT`),
**FE 383** (F26 H12). Fresh collision check found repo-wide max 380, matching the
dispatch's expectation, so no renumbering was needed. Nine open items surfaced and
reported; none of them worked on.
