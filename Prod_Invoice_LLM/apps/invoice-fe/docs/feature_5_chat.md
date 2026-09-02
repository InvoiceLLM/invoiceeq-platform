# Feature 5: Semantic Chat Assistant & SQL Audit Drawer — **SAGE Agent**
**SAGE** (Invoice Intelligence Chat) powers this screen. Build the conversational invoice analyst RAG chat box, document citation connectors, and database query inspection drawers.

### Theme & Styling Specifications

- Chat Bubble:
  - User: `bg-[#1E293B] text-slate-100 rounded-2xl rounded-tr-none`.
  - Assistant: `bg-gradient-to-r from-blue-950/20 to-purple-950/20 border border-blue-800/40 rounded-2xl rounded-tl-none`.
- Citation Pills: `bg-[#1E293B] border border-[#222D3D] text-slate-300 hover:text-white cursor-pointer px-3 py-1 rounded-full text-xs`.
- SQL Code block: `bg-[#0B0F19] text-[#10B981] border border-[#222D3D] font-mono rounded-lg p-3`.

### File Coordinates

- Chat Page: `apps/invoice-fe/app/chat/page.tsx` ✅ _(created 2026-07-22)_
- Chat Messages Panel: `apps/invoice-fe/components/chat/MessageBubble.tsx` ✅ _(created 2026-07-22 — exports `MessageBubble` + `MessageStream`)_
- Chat Window Layout: `apps/invoice-fe/components/chat/ChatWindow.tsx` ✅ _(created 2026-07-22 — 2-column layout with thread sidebar + input bar)_
- Citation Pill: `apps/invoice-fe/components/chat/CitationPill.tsx` ✅ _(created 2026-07-22)_
- SQL Audit Drawer: `apps/invoice-fe/components/chat/SqlAuditDrawer.tsx` ✅ _(created 2026-07-22)_
- State Hook: `apps/invoice-fe/hooks/useChatSession.ts` ✅ _(created 2026-07-22)_
- Types: `apps/invoice-fe/types/chat.ts` ✅ _(created 2026-07-22)_
- Proxy Routes: `app/api/chat/sessions/route.ts`, `app/api/chat/sessions/[sessionId]/route.ts` (`GET`/`DELETE`, plus `PUT` added 2026-08-12 for Gap 216), `app/api/chat/sessions/[sessionId]/message/route.ts` ✅ _(all created 2026-07-22)_, `app/api/chat/messages/[messageId]/feedback/route.ts` ✅ _(created 2026-07-27, Gap 27)_
- E2E: `apps/invoice-fe/e2e/chat-thread-rename.spec.ts` ✅ _(created 2026-08-12, Gap 216)_

### P0 Fix: Chat never actually worked through the real UI (Gap 22, Jul 24, 2026)
Everything above was built and marked complete on 2026-07-22, but never actually exercised against a live backend until real end-to-end browser testing on Jul 24 — the benchmark harness that reported "95.2% RAG chat passed" calls the backend directly, bypassing this entire FE layer, so this class of bug was invisible to it.

Every single message send failed with `422 Unprocessable Entity`. Root cause: `useChatSession.ts::sendMessage()` posted `{message: text.trim()}`, and `types/chat.ts::SendMessageRequest` documented that same (wrong) shape — but the backend's `routers/chat.py::MessageCreate` requires `{content: text}`. Three more silent mismatches (wrong/`undefined` data, not errors) found in the same pass:
- `GET /chat/sessions` returns a bare `SessionResponse[]` array; `fetchSessions()` read `res.data.sessions`.
- `GET /chat/sessions/{id}` returns a bare `MessageResponse[]` array; `selectSession()` read `res.data.messages`.
- `POST .../message`'s response is the flat `ChatMessage` object; `sendMessage()` read `res.data.message`.
- `Citation.page_number` didn't match the backend's `CitationResponse.page` — would have rendered "p.undefined" on every RAG citation pill.

Fixed all five in `useChatSession.ts`, `types/chat.ts`, and `CitationPill.tsx` — see `be_features_tracker.md`/`fe_features_tracker.md` Gap 22 for the full writeup. Verified live: 3 real questions against a real ingested invoice, correct SQL-routed answers, zero console errors.

### Fix: Deleting a chat thread left it on screen (Gap 177, Aug 11, 2026)
Thread deletion (`ChatWindow.tsx`'s header button and the per-thread trash icon in `ThreadSidebar`, both → `useChatSession.ts::deleteSession` → `app/api/chat/sessions/[sessionId]/route.ts` → BE `DELETE /chat/sessions/{session_id}`, 204) deleted the row in Postgres but never removed it from the sidebar — it reappeared only after a reload, and kept matching the Gap 149 thread search in the meantime (that was the whole of Gap 180; the search filter itself was never broken). Nothing in this feature was at fault: the bug was in the shared proxy helper, which could not construct a 204 response and returned 500 for it — see `feature_1_layout_theme.md`'s "API Call Path → Null-body statuses" for the mechanism and the fix. `deleteSession` is unchanged; it now takes its success branch because the route handler finally returns the backend's real 204.

In the same pass the header button was relabelled **"Clear Chat" → "Delete Chat"** (`ChatWindow.tsx`, in the slim SAGE agent strip). It has always called the same `onDeleteSession(activeSessionId)` handler as the sidebar trash icon — it deletes the entire thread. There is no clear-messages-keep-thread capability in the FE or the backend, and none was added: the label was corrected to describe what the button does, since per-thread delete already covers the need.

### Fix: Renaming a chat thread never reached the backend (Gap 216, Aug 12, 2026)
Inline thread rename (the pencil icon in `ChatWindow.tsx`'s `ThreadSidebar`, added by Gap 149 → `useChatSession.ts::renameSession` → `PUT /api/chat/sessions/{id}`) changed the sidebar label and nothing else: the title reverted on the next load, with no error shown in between. Two separate holes, both real:
- `app/api/chat/sessions/[sessionId]/route.ts` exported only `GET` and `DELETE`, so Next.js rejected the method with a 405 before any handler ran.
- **The backend had no rename endpoint either** — the tracker entry left this open; `routers/chat.py` turned out to have no `PUT` on a session at all. So this was not the proxy-only fix it first looked like.
- `renameSession`'s `catch` applied the new title to local React state anyway. That branch was the one that always ran, which is exactly why the failure was silent.

**Fixed**: `route.ts` gained a `PUT` export through the same `proxyJson` helper as its siblings, backed by a new `routers/chat.py::rename_session()` (`PUT /chat/sessions/{session_id}`, title-only, tenant-scoped 404/403, 400 on a whitespace-only title — see `apps/invoice-be/docs/feature_6_rag.md`). `renameSession` now awaits the real response, applies the title the backend echoes back (so server-side normalisation such as trimming is what lands on screen), and its `catch` sets `error` ("Failed to rename this chat session.") — rendered by ChatWindow's existing error banner — instead of faking success. Same shape as `deleteSession`, which already only mutated state on success.

**Verified**: `npx tsc --noEmit` clean; new `e2e/chat-thread-rename.spec.ts` (3 tests) passing against a real dev server. The two page-driven tests were confirmed to fail against the un-fixed hook before being accepted. A scope limit was found and is documented in that spec's header rather than papered over: `page.route()` intercepts in the browser, *before* Next.js is reached, so a stubbed `PUT` cannot tell whether the proxy route exists — proven by deleting the `PUT` export and watching both page tests still pass. The third test therefore drives the dev server through Playwright's `request` fixture and asserts the response is not a 405; that one does fail without the export.

### Fix: Thumbs-down crashed the chat screen instead of opening the triage dialog (Gap 239, Aug 17, 2026)
`components/chat/ThumbsDownTriage.tsx` is mounted unconditionally in `MessageBubble.tsx` (kept in the tree, toggled via an `isOpen` prop, not conditionally rendered) so its state survives being opened/closed repeatedly. It had an early return (`if (!isOpen) return null;`) with a `useEffect` (the one loading the category vocabulary) declared *after* it. While closed, React ran the hooks up to the early return and stopped there; the moment thumbs-down flipped `isOpen` to `true`, the same component instance re-rendered, ran the same hooks, but no longer returned early — calling one more hook than the previous render. A differing hook count across renders of one instance is a React Rules-of-Hooks violation, thrown during render/commit ("Rendered fewer hooks than expected" / minified #310) — exactly the reported generic "Application error: a client-side exception has occurred," and consistent with everything already ruled out on the API/type/Provider side before this was found.

**Fixed**: moved the effect (and the `ensureCategories` helper it calls) to above the early return, alongside the component's other unconditional hooks — pure reordering, no logic change. Also confirmed why this shipped unnoticed: `package.json` has no ESLint/`eslint-plugin-react-hooks` at all, and no Playwright spec exercised the thumbs-down click — both worth a fast-follow.

**Verified**: `npx tsc --noEmit` clean.

### Fix: Chat replies had no rich formatting — worse, they leaked raw markdown syntax (Gap 229, Aug 17, 2026)
`MessageBubble.tsx`'s renderer was a hand-rolled regex supporting only `**bold**`/`` `code` ``/`*italic*`. The backend was already sending real GFM markdown this renderer couldn't handle: SQL-route replies append a real pipe table (`### Query Results` + `|`-delimited rows, `agents/query_agent.py`), RAG-route replies append real markdown links (`[Source: ...](file:///...)`) — so users saw literal `###`/`|`/`[...](...)` characters, not just plain-feeling prose. The renderer's own comment cited "no react-markdown installed, avoid an ES-module dep + `transpilePackages`" as the reason for the regex approach; didn't hold up on inspection — `react-markdown` is plain ESM/CJS-dual and works in a `"use client"` component on Next 14.2.3 with no extra config.

**Fixed**: added `react-markdown` + `remark-gfm` (tables/strikethrough), swapped the renderer, added a `components` map to keep the existing dark-theme palette for bold/code and add matching styles for the newly-renderable elements (lists, tables, headings, links, blockquotes). Also added a `FORMATTING` line to the backend's RAG/CHAT system prompts instructing bullet lists for multi-item answers — the renderer swap alone only fixes backend-constructed markdown, not LLM-authored prose structure (see `apps/invoice-be/docs/feature_6_rag.md`).

**Verified**: `npx tsc --noEmit` clean.

### Tasks

- [x] **Task 5.1: Build Conversational Message Thread Interface**
  - Implemented scroll-to-bottom chat bubble container with markdown formatting rendering.
  - Implemented thread selectors and a `New Chat` action clearing active states.
  - Files: `ChatWindow.tsx`, `MessageBubble.tsx`
- [x] **Task 5.2: Integrate Interactive Citations**
  - Parsed `citations[]` from the chat API response and rendered as interactive pills.
  - Bound pills to navigate to `/invoices/review/{invoice_id}?page={n}` — originally coded as `/audit?invoice_id=...`, a route that never existed; fixed 2026-07-27 alongside Gap 26/`be_features_tracker.md` Gap 53 (see `feature_4_auditor.md`).
  - File: `CitationPill.tsx`
- [x] **Task 5.3: Build Expandable SQL Drawer**
  - Created a collapsible accordion container titled `Executed SQL Query & Data Sources`.
  - Formatted SQL code in a green monospace code block with copy-to-clipboard action.
  - File: `SqlAuditDrawer.tsx`
- [x] **Task 5.4: Bind Chat Queries to Backend**
  - Coded async submit hook (`useChatSession`) posting prompts via 3 Next.js proxy route handlers.
  - Includes optimistic user bubble insertion, error rollback, and session title auto-update.
  - Files: `useChatSession.ts`, 3 proxy `route.ts` files
- [x] **Task 5.6: Suggestion Chips (Gap 6, 2026-07-27)**
  - New `SuggestionChips` component inside `ChatWindow.tsx`, shown only when the active session has zero messages — clicking a chip calls `onSendMessage` directly (auto-submit, not just auto-fill). Not part of this feature's original scope, tracked as a separate enhancement.
- [x] **Task 5.5: Per-answer feedback (Gap 27, 2026-07-27)**
  - New `FeedbackVote` component inside `MessageBubble.tsx` — a thumbs up/down pair shown only on assistant messages, next to the timestamp. Optimistic update with rollback on failure; clicking the currently-active thumb again clears the vote (`DELETE`) instead of re-sending it, giving a normal toggle interaction.
  - `types/chat.ts::ChatMessage` gained `feedback?: "up" | "down" | null`, populated by the backend on session reload (`be_features_tracker.md` Gap 54).
  - Calls `PUT`/`DELETE /api/chat/messages/{id}/feedback` via the new proxy route.

### Verification Plan

- **TypeScript Compile**: `npx tsc --noEmit` — ✅ **0 errors** (verified 2026-07-22; re-verified 2026-08-12 with the Gap 216 changes)
- **E2E**: `npx playwright test e2e/chat-thread-rename.spec.ts` — ✅ 3 passed (2026-08-12). Needs the Next dev server on the configured Playwright port; no FastAPI backend is required (the page tests stub `/api/chat/**` in the browser, and the proxy-reachability test asserts "not 405", not a success status, precisely so it does not depend on one).
- **Manual Verification**: Launch the Chat screen. Type a query (e.g., _"What is my total spend?"_), confirm the SQL drawer displays the query, and click a citation pill to check its behavior.


---

## Additive section — attached reference documents (BE Feature 26 / Gap 366, 2026-09-01)

Additive only, per hard rule 4 — nothing above this line is changed. The
backend design record for this is `apps/invoice-be/docs/feature_26_chat_attached_documents.md`;
this section specifies only the chat FE surface.

**Status: specified, NOT built.** The backend (three endpoints, the extraction
profile, the deterministic matcher/comparator, and the pre-route gate) shipped
on 2026-09-01. The FE work below was the pre-agreed cut line for that time-box
and was deliberately left unbuilt rather than half-built. It is written down here
so the surface is specified and the next session does not have to re-derive it.

### What the user does

Attach a PDF **purchase order or quotation** to a chat session, then ask a
question grounded in it — "does this bill match what we agreed?". The assistant
finds the corresponding invoice(s), **asks the user to confirm the match before
saying anything financial**, and then reports a diff that was computed
deterministically in Python (the LLM only narrates it).

### File Coordinates

- **`components/chat/ChatWindow.tsx`** — the composer's `InputBar` is co-located
  in this file, not its own module. Adds a paperclip button plus a hidden
  `<input type="file">`. **Lift `components/ingestion/DropZone.tsx`'s existing
  guards rather than writing new ones** — that component already has the PDF
  `accept` attribute, the byte-size cap and the filename-suffix check, and a
  second, subtly different set of client guards for the same backend rules is
  how the two drift apart. PDF-only; images are a separate Phase 2 item
  (`apps/invoice-be/docs/phase_2_enhancements.md` §2), not this one.
- **`types/chat.ts`** — `ChatMessage` has no attachment field today. Add an
  optional attachment reference plus the `attachment_id` the send path carries.
- **`hooks/useChatSession.ts`** — sends `attachment_id` on the message when one
  is attached, and re-reads the attachment on session reload via
  `GET /chat/attachments/{id}` (this is exactly why the backend persists a row
  rather than keeping session scratch — the existing reload/reattach path would
  otherwise lose it).
- **NEW `components/chat/AttachmentMatchConfirm.tsx`** — renders the
  `attachment_match_confirmation` payload: the candidate invoices, whether they
  were found by exact PO number (tier 1) or by name+date (tier 2, and therefore
  worth checking), and a confirm action posting to
  `POST /chat/attachments/{id}/confirm-matches`.

### Rules this surface must respect

1. **The confirmation step is not skippable.** Until the user confirms, the
   backend returns a confirmation payload and no figures at all. The FE must
   render that as a confirmation prompt, never as an answer, and must not
   auto-confirm a single candidate on the user's behalf — a one-candidate tier-2
   guess is still a guess.
2. **Zero matches offers manual entry.** The payload sets
   `requires_manual_entry`; the FE asks for an invoice number rather than
   showing an empty list.
3. **Suggested actions are links, never buttons that act.** The backend returns
   0–3 deep-links whose preconditions it has already checked. Render them as
   navigation, the same way `ThumbsDownTriage.tsx` consumes the triage
   `redirect` block. Chat never invokes a mutating endpoint.
4. **Client-side caps mirror the server, they do not replace it.** 10 MB, PDF
   only, 5 per session are all enforced server-side (413 / 415 / 409); the
   client checks are for a fast error message, and the server responses still
   need surfacing.

### Verification Plan for this section (when built)

- `npx tsc --noEmit` clean.
- A Playwright case that attaches a PDF, asserts the **confirmation prompt**
  renders instead of an answer, confirms a candidate, and only then asserts a
  figure appears.
- A case asserting an oversized file and a non-PDF are both rejected with the
  server's message surfaced, not swallowed.
