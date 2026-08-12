# Gap 180 — Chat "Find Thread" inconsistent behavior — dev verification

Checkpoint 1 of the 17-checkpoint remediation plan. Pure verification, no
code changes. Real local dev stack (real backend on :8000, real Postgres,
`invoice-fe` on :3001 with `DISABLE_CLERK_AUTH=true` — see Gap 152's README
for why that bypass is this repo's own established pattern, not a mock of
anything under test here — the chat sessions, search filter, and delete calls
are all real, hitting the real `/chat/sessions*` backend endpoints). Playwright
headless Chromium, 2026-08-11.

## Test plan executed

Created 3 real chat sessions via the real "New Chat" button + backend
`POST /chat/sessions`, renamed them to distinct/overlapping titles via the
real rename flow (`PUT /chat/sessions/{id}`): "Acme Hardware Invoice Q1",
"Globex Services Statement", "Zeta Corp Follow-up" (`1_three_threads_renamed.png`).
Pre-existing sessions from earlier test work (Gap 13/54/55 verification
threads, "New Chat"s, dated auto-titled sessions) were already present in
this tenant's history and left alone — 20 sessions total in the sidebar for
this run.

### 1. Filter logic in isolation — works correctly, no bug found

| Query | Expected | Actual | Screenshot |
|---|---|---|---|
| `acme` (lowercase) | Matches "Acme Hardware Invoice Q1" only | ✅ `["Acme Hardware Invoice Q1"]` | `2_search_acme_lowercase_match.png` |
| `ACME` (uppercase) | Same, case-insensitive | ✅ `["Acme Hardware Invoice Q1"]` | — |
| `Globex Services Statement` (full title) | Exact match | ✅ `["Globex Services Statement"]` | — |
| `Follow-up` (mid/end substring) | Matches "Zeta Corp Follow-up" | ✅ `["Zeta Corp Follow-up"]` | — |
| `xyznonexistent` (no match) | Empty list + "No matching conversations." message | ✅ empty list, message shown | `3_search_no_match_message.png` |
| cleared | All 20 sessions return | ✅ | — |

`ThreadSidebar`'s `filteredSessions = sessions.filter(s =>
(s.title||"New Chat").toLowerCase().includes(searchQuery.toLowerCase()))`
(`ChatWindow.tsx:79-80`) is a plain client-side array filter over
already-loaded state, re-evaluated synchronously on every keystroke — there
is no debounce, no async call, and none was needed to reproduce lag; typing
felt instant in every case above. **No defect found in the filter/search
logic itself.**

### 2. Delete + search interaction — reproduces the Gap 177 symptom exactly

Clicked the trash icon on "Zeta Corp Follow-up". Sequence observed:

1. Backend `DELETE /chat/sessions/{id}` call → Next.js route proxy → **500**
   (`fe_dev_server_log_excerpt.txt` has the full stack: `proxyJson()`
   throwing `TypeError: Response constructor: Invalid response status code
   204`, matching Gap 177's root-cause analysis in `fe_features_tracker.md`
   exactly).
2. FE shows a red error banner "Failed to delete the chat session."
   (`useChatSession.ts::deleteSession()`'s catch path) and the thread **stays
   in the sidebar** — `4_after_delete_click_error_banner_thread_lingers.png`.
3. Searching `Zeta` **still finds it** — `5_search_still_finds_deleted_ghost_thread.png`
   — a genuinely-deleted thread is a live, returned search result. This is
   the "inconsistent" behavior a user would report: the thread they just
   deleted keeps showing up.
4. Direct Postgres check confirms the backend actually deleted the row
   (`SELECT ... WHERE id = '...'` → 0 rows — see log excerpt) — the delete
   is real and committed, only the FE's in-memory `sessions` state (and thus
   the search index over it) never learned about it.
5. Full page reload (`page.reload()`, re-fetches `GET /chat/sessions` fresh)
   → thread is genuinely gone from the sidebar —
   `6_after_full_reload_thread_actually_gone.png`.

## Assessment: Gap 180 is a Gap 177 symptom, not an independent bug

The architect's hypothesis is confirmed correct: `searchQuery`/
`filteredSessions` (`ChatWindow.tsx:75-80`) has no defect of its own — every
partial/full/case-varied/substring query returned exactly the right set,
instantly, both before and after the delete-induced ghost. The only way a
stale/deleted thread appears in search results is because it never left the
`sessions` array Gap 177 already identified as not being purged on a failed
(500) delete response — search is just reading that same stale array. Fixing
Gap 177 (the `proxyJson()` null-body handling for 204/205/304) removes this
symptom for free; no separate change to the search/filter code is needed.

## Verdict

**Gap 180: NEEDS-FURTHER-INVESTIGATION downgraded to CONFIRMED — symptom of
Gap 177, not an independent defect.** Precise repro: delete a thread → it
lingers in the sidebar and in search results (not "missing" or "wrong
results" — a *stale positive* result) until a full reload. The filter logic
itself (case sensitivity, partial match, debounce/timing) was tested
directly and has no defect. Recommend: don't schedule separate work against
`ChatWindow.tsx`'s search code; closing Gap 177 should be verified to also
close this report. If a user's original complaint about "find thread" turns
out to describe something other than ghost-deleted-thread pollution (e.g. an
observation made before ever deleting a thread), that would need a fresh,
more specific repro from the reporter — nothing else "inconsistent" was
found in this pass.
