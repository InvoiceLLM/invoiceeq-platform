# Checkpoint 2 -- Gap 177 fix retest (chat delete, webhook delete, "Delete Chat" rename) + Gap 180 dependent closure

Note: this file was written after execution completed rather than before, same
deviation from CONVENTIONS.md noted in Checkpoint 1's tasklist -- not repeating
past this point.

- [x] Read `.claude/CONVENTIONS.md`, `lib/backendProxy.ts` (confirm the shipped
      fix), `fe_features_tracker.md` Gap 177/180 entries, `ChatWindow.tsx`
      button rename, `feature_5_chat.md`, `app/settings/webhooks/page.tsx`,
      `app/api/webhooks/[id]/route.ts`
- [x] Start `docker compose up -d` (Postgres/Redis/Chroma/Azurite), real
      backend (`uvicorn`, :8000, `ALLOW_MOCK_AUTH=true`), real `invoice-fe`
      (:3001, `DISABLE_CLERK_AUTH=true`)
- [x] Chat thread delete via sidebar trash icon: create thread, delete,
      capture network status + DB row check
- [x] Chat thread delete via header "Delete Chat" button: create thread,
      select, delete, capture network status + DB row check + confirm label
      rename shipped
- [x] Gap 180 retest: create thread, search (found), delete, search again
      immediately with no reload (not found) -- confirms the ghost-thread
      symptom Checkpoint 1 documented no longer reproduces
- [x] Webhook delete: create webhook, delete via trash icon (handle native
      `confirm()` dialog), capture network status + DB row check -- first
      pass had a stale-locator false read, rerun twice cleanly to confirm
- [x] File evidence: `invoice-fe/docs/test_evidence/gap177_checkpoint2_retest/`
      (12 screenshots, network/console logs, FE dev-server log excerpt, DB
      query output, README with verdicts)
- [x] Update `invoice-fe/docs/test_coverage_map.md` (Gap 180 row + new Gap 177
      retest row)
- [x] Update `fe_features_tracker.md` Gap 180 entry to `[x]` closed,
      referencing this retest -- Gap 177's own entry left untouched per
      instructions
- [x] Flag incidental unrelated finding (chat rename `PUT` 405, no such route
      handler, silent client-only fallback) in the evidence README -- not
      fixed, out of scope
- [x] Clean up: remove temp Playwright scripts and a stray garbled-path
      output directory accidentally created inside the repo tree by the first
      script run

**Final status:** All three retest items PASS. Chat thread delete (both entry
points) and webhook delete now return 204 and update the UI immediately with
no reload; direct Postgres queries confirm every deleted row is actually
gone. Gap 180 CONFIRMED CLOSED as a direct, automatic consequence of the Gap
177 fix -- no independent code change needed, tracker updated to `[x]`. No
code changed by this checkpoint.
