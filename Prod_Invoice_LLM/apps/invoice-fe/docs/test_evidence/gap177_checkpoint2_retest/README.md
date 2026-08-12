# Gap 177 fix retest + Gap 180 closure verification -- Checkpoint 2

Checkpoint 2 of the defect remediation plan. Pure verification, no code
changes made by this pass. Real local dev stack: Postgres/Redis/Chroma/Azurite
via `docker compose` (project root `Prod_Invoice_LLM/`), real backend
(`uvicorn main:app`, port 8000, `ALLOW_MOCK_AUTH=true`), real `invoice-fe`
Next.js dev server (port 3001, `DISABLE_CLERK_AUTH=true` -- the same
established bypass pattern used in Checkpoint 1's gap152/gap180 evidence, not
a mock of anything under test here). Playwright headless Chromium,
1280x800, 2026-08-11. Two script runs were used: a combined chat+webhook
script (`gap177_retest_run.js`, run twice -- once with a broken screenshot
output path that was fixed and rerun cleanly) and a dedicated
webhook-only script (`gap177_webhook_retest.js`) written to get
unambiguous network-level evidence for the webhook delete specifically.
Scripts are not committed (ephemeral verification tooling, per this repo's
test_evidence convention of filing outputs, not scaffolding).

## 1. Chat thread delete -- sidebar trash icon

Created a real thread via `POST /chat/sessions`, renamed it to "GAP177
Retest Trash Icon Delete", clicked the per-thread trash icon.

- Network: `DELETE /api/chat/sessions/{id}` -> **204** (was 500 pre-fix; see
  Gap 177's own root-cause entry and `gap180_chat_find_thread/README.md` for
  the pre-fix 500 trace).
- UI: thread removed from the sidebar immediately, no reload
  (`1_thread_created_renamed_trash_test.png` -> `2_after_trash_icon_delete_no_reload.png`).
- DB: row for `400fa3ed-61de-4eed-9c2a-282fb77e3326` (first run) and
  `ec979f46-2a32-4c72-bb7f-d02d02550775` (clean rerun) confirmed **0 rows**
  in `chatsession` -- `db_verification_queries.txt`.

**PASS.**

## 2. Chat thread delete -- header "Delete Chat" button (renamed from "Clear Chat")

Created a second thread, renamed to "GAP177 Retest Delete Chat Button",
selected it, clicked the header's "Delete Chat" button (screenshot
`3_thread_created_renamed_header_test.png` shows the button's new label,
confirming the N-19 rename shipped).

- Network: `DELETE /api/chat/sessions/{id}` -> **204**.
- UI: thread removed immediately, no reload
  (`4_after_delete_chat_button_no_reload.png`).
- DB: row for `8243ffb7-c814-4198-82c2-3edb21073b93` (first run) and
  `eb7e06f4-264b-4e38-a9fa-48aeb31a085d` (clean rerun) confirmed **0 rows**.

Confirms the button now behaves exactly as documented in
`feature_5_chat.md`'s "Fix" section -- same `onDeleteSession` handler as the
trash icon, deletes the whole thread, label now matches behavior.

**PASS.**

## 3. Gap 180 retest -- Find Thread after a real delete

Created a third thread, "GAP180 Retest FindThread Ghost". Searched
"FindThread Ghost" before deleting it -> 1 result, thread found
(`6_gap180_search_before_delete_found.png` -- establishes the search itself
still works correctly, consistent with Checkpoint 1's finding that the
filter logic was never the defect). Cleared the search, deleted the thread
via the trash icon (`DELETE` -> 204, confirmed in
`chat_and_webhook_network_console_log.txt`), then searched the exact same
query again immediately, no reload.

- Result: **0 matches**, "No matching conversations." shown
  (`7_gap180_search_after_delete_gone.png`) -- the ghost-thread symptom
  Checkpoint 1 documented (deleted thread still matching search results) does
  not reproduce now that the underlying delete actually succeeds and the
  thread leaves `sessions` state immediately.
- DB: row for `595da805-1a42-45ac-8091-491f5b3b516a` confirmed **0 rows**.

**Gap 180: CONFIRMED CLOSED as a direct result of the Gap 177 fix.** No
independent code change to `ChatWindow.tsx`'s search/filter was needed or
made, matching the architect's original prediction in the Gap 177 tracker
entry ("expected to close automatically once 177 ships").

## 4. Webhook subscription delete

Settings -> Webhooks. Created a real webhook (`POST /api/webhooks`, target
URL `https://example.com/gap177-retest-webhook` and `-v2`, event
`invoice.completed`), confirmed it listed
(`11_webhook_in_list_before_delete.png`), clicked its trash icon, accepted
the native `confirm()` dialog (`window.confirm` is used here, unlike chat's
trash icon which has none -- captured via Playwright's `page.on('dialog')`).

- Network: `DELETE /api/webhooks/{id}` -> **204** (confirmed 3 separate
  times across both script runs -- see
  `webhook_dedicated_rerun_network_log.txt` and
  `fe_dev_server_log_delete_calls_excerpt.txt`).
- UI: webhook disappears from the list immediately, no reload
  (`12_webhook_after_delete_no_reload.png` -- back to the "No Webhooks
  Registered" empty state).
- DB: all 3 created-and-deleted webhook IDs confirmed **0 rows**, and the
  full `webhook_subscriptions` table is empty (0 remaining rows) --
  `db_verification_queries.txt`.

**PASS.**

## Note on one measurement anomaly, not treated as a functional defect

The very first (uncleaned) script run's in-page assertion briefly reported
the deleted webhook's URL text as still present (count=1) even though the
same run's dev-server log shows that DELETE call actually returned 200
(not 204 -- Next dev-mode's on-demand compile of `/api/webhooks/[id]` added
about 2 seconds to that one request; see the `bee0f819...` line in
`fe_dev_server_log_delete_calls_excerpt.txt`). This did not reproduce in
either of two subsequent clean reruns -- an imprecise non-exact text
locator in that first pass is the likely cause, not a real UI bug. Both
reruns show 204 and immediate, correct disappearance using a precise
`exact: true` locator and an explicit `page.waitForResponse()`-gated
assertion. Backend code (`routers/webhooks.py:148`) unconditionally
declares `status_code=status.HTTP_204_NO_CONTENT`, so a 200 there would
itself be unexpected; treating the single first-run reading as noise given
it did not reproduce and the DB state is correct either way.

## Incidental finding -- out of scope, flagged for the tracker, not fixed here

Every rename attempt during this retest (used to give each test thread a
distinct, searchable title for scenarios 1-3 above) logged
`PUT /api/chat/sessions/{id} 405` in the FE dev server
(`fe_dev_server_log_delete_calls_excerpt.txt`, between the GET and DELETE
lines for each session). Source-confirmed:
`app/api/chat/sessions/[sessionId]/route.ts` exports only `GET` and
`DELETE` handlers -- there is no `PUT` handler at all, so Next.js's App
Router returns its default 405 for that method. `useChatSession.ts`'s
`renameSession` (line 194) calls `apiClient.put('/chat/sessions/' + id, ...)`
expecting one to exist, and its `catch` block (line 198) silently falls
back to a client-state-only rename -- the UI shows the new title correctly
(as seen in every screenshot above), but it is never persisted server-side.
A reload, or opening the thread from a different session, would revert the
title to whatever the backend actually has stored. This is unrelated to
Gap 177/180 (it did not block or affect delete behavior on renamed-in-UI-only
threads in any of the three scenarios above) and was not part of this
checkpoint's scope, so it was not fixed here. Recommend filing as a new
tracker gap for a future checkpoint: either the missing `PUT` handler +
backend route need to be added, or Gap 149 (closed 2026-08-07, "added...
inline thread title editing") never actually persisted renames past the FE
fallback path and needs reopening.
