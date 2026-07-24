# Feature 5: Semantic Chat Assistant & SQL Audit Drawer
Build the conversational invoice analyst RAG chat box, document citation connectors, and database query inspection drawers.

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
- Proxy Routes: `app/api/chat/sessions/route.ts`, `app/api/chat/sessions/[sessionId]/route.ts`, `app/api/chat/sessions/[sessionId]/message/route.ts` ✅ _(all created 2026-07-22)_

### Tasks

- [x] **Task 5.1: Build Conversational Message Thread Interface**
  - Implemented scroll-to-bottom chat bubble container with markdown formatting rendering.
  - Implemented thread selectors and a `New Chat` action clearing active states.
  - Files: `ChatWindow.tsx`, `MessageBubble.tsx`
- [x] **Task 5.2: Integrate Interactive Citations**
  - Parsed `citations[]` from the chat API response and rendered as interactive pills.
  - Bound pills to navigate to `/audit?invoice_id={id}&page={n}`.
  - File: `CitationPill.tsx`
- [x] **Task 5.3: Build Expandable SQL Drawer**
  - Created a collapsible accordion container titled `Executed SQL Query & Data Sources`.
  - Formatted SQL code in a green monospace code block with copy-to-clipboard action.
  - File: `SqlAuditDrawer.tsx`
- [x] **Task 5.4: Bind Chat Queries to Backend**
  - Coded async submit hook (`useChatSession`) posting prompts via 3 Next.js proxy route handlers.
  - Includes optimistic user bubble insertion, error rollback, and session title auto-update.
  - Files: `useChatSession.ts`, 3 proxy `route.ts` files

### Verification Plan

- **TypeScript Compile**: `npx tsc --noEmit` — ✅ **0 errors** (verified 2026-07-22)
- **Manual Verification**: Launch the Chat screen. Type a query (e.g., _"What is my total spend?"_), confirm the SQL drawer displays the query, and click a citation pill to check its behavior.
