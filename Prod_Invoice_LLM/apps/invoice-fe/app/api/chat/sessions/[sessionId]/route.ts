// =============================================================================
// FILE: app/api/chat/sessions/[sessionId]/route.ts
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: When the user clicks a thread in the sidebar, the frontend
//   needs to load the full message history for that session.  This Route
//   Handler proxies that GET to the backend, which returns the session
//   metadata + all messages in chronological order.
//   The [sessionId] dynamic segment is extracted by Next.js and injected
//   into `params` — it is then spliced into the backend URL path.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

// GET /api/chat/sessions/[sessionId]
// WHY: Fetches a single session together with its full ChatMessage array.
//   Called by useChatSession.selectSession(id) whenever the user switches
//   threads.  The response is typed as GetSessionResponse in types/chat.ts.
export async function GET(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  // Inject the dynamic sessionId into the backend path so the backend can
  // apply tenant-scoped row-level security before returning records.
  return proxyJson(request, `/chat/sessions/${params.sessionId}`);
}

// PUT /api/chat/sessions/[sessionId]
// WHY (Gap 216): useChatSession.renameSession() has called PUT on this path
//   since the inline thread-rename UI landed (Gap 149), but this file only
//   exported GET and DELETE — so Next.js answered 405 and the rename was never
//   written anywhere. Backed by routers/chat.py::rename_session(), which takes
//   `{ title }` and re-checks tenant ownership before writing.
export async function PUT(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  return proxyJson(request, `/chat/sessions/${params.sessionId}`);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  return proxyJson(request, `/chat/sessions/${params.sessionId}`);
}
