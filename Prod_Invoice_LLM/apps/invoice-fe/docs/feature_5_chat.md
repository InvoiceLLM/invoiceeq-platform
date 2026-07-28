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
- Proxy Routes: `app/api/chat/sessions/route.ts`, `app/api/chat/sessions/[sessionId]/route.ts`, `app/api/chat/sessions/[sessionId]/message/route.ts` ✅ _(all created 2026-07-22)_, `app/api/chat/messages/[messageId]/feedback/route.ts` ✅ _(created 2026-07-27, Gap 27)_

### P0 Fix: Chat never actually worked through the real UI (Gap 22, Jul 24, 2026)
Everything above was built and marked complete on 2026-07-22, but never actually exercised against a live backend until real end-to-end browser testing on Jul 24 — the benchmark harness that reported "95.2% RAG chat passed" calls the backend directly, bypassing this entire FE layer, so this class of bug was invisible to it.

Every single message send failed with `422 Unprocessable Entity`. Root cause: `useChatSession.ts::sendMessage()` posted `{message: text.trim()}`, and `types/chat.ts::SendMessageRequest` documented that same (wrong) shape — but the backend's `routers/chat.py::MessageCreate` requires `{content: text}`. Three more silent mismatches (wrong/`undefined` data, not errors) found in the same pass:
- `GET /chat/sessions` returns a bare `SessionResponse[]` array; `fetchSessions()` read `res.data.sessions`.
- `GET /chat/sessions/{id}` returns a bare `MessageResponse[]` array; `selectSession()` read `res.data.messages`.
- `POST .../message`'s response is the flat `ChatMessage` object; `sendMessage()` read `res.data.message`.
- `Citation.page_number` didn't match the backend's `CitationResponse.page` — would have rendered "p.undefined" on every RAG citation pill.

Fixed all five in `useChatSession.ts`, `types/chat.ts`, and `CitationPill.tsx` — see `be_features_tracker.md`/`fe_features_tracker.md` Gap 22 for the full writeup. Verified live: 3 real questions against a real ingested invoice, correct SQL-routed answers, zero console errors.

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

- **TypeScript Compile**: `npx tsc --noEmit` — ✅ **0 errors** (verified 2026-07-22)
- **Manual Verification**: Launch the Chat screen. Type a query (e.g., _"What is my total spend?"_), confirm the SQL drawer displays the query, and click a citation pill to check its behavior.
