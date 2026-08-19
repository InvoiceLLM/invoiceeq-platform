// =============================================================================
// FILE: app/api/chat/sessions/[sessionId]/message/route.ts
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: This is the most critical proxy in the chat feature.  It
//   forwards the user's message to the FastAPI backend, which runs
//   run_query_agent() — the LangGraph ReAct loop that classifies the query
//   and routes it to one of three execution paths:
//     SQL  → generates a tenant-scoped SELECT query, executes it via SQLAlchemy,
//             returns generated_sql + result summary
//     RAG  → queries ChromaDB with BAAI/bge-m3 embeddings, returns citations[]
//     CHAT → general LLM conversation without DB access
//   The backend returns a ChatMessage with all optional fields populated
//   depending on which path was taken.  This proxy never inspects the body —
//   it passes it through verbatim so future backend changes need no FE update.
//
// GAP FIX: "Failed to send message" on long chat responses
//   The LangGraph agent makes multiple sequential OpenAI calls (20-36s total).
//   The generic proxyJson() / platform default timeout was killing the
//   connection before the backend finished, causing the FE's catch block to
//   surface "Failed to send message. Please try again."  Two fixes together:
//   (1) maxDuration = 120 raises the Next.js route execution limit to 120s.
//   (2) The fetch() below uses AbortSignal.timeout(110_000) so the proxy
//       itself times out cleanly before the platform does (110s < 120s),
//       returning a useful 504 instead of a torn TCP connection.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Raise this route's execution limit to 120 seconds.
 * The chat agent makes multiple sequential LLM calls and can legitimately
 * take 20-40s on a cold path.  Without this the platform cuts the connection
 * at its default limit and the FE catches a network error.
 */
export const maxDuration = 120;

// POST /api/chat/sessions/[sessionId]/message
// WHY: Sends the user's typed message to the backend query agent.
//   Called by useChatSession.sendMessage() after the optimistic user bubble
//   is already added to the UI.  The response (assistant ChatMessage) is
//   appended to the messages array so the stream renders immediately.
export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  // The path matches the backend route: POST /api/v1/chat/sessions/{id}/message
  // which maps to the run_query_agent() entrypoint in feature_6_rag.md.
  //
  // Use a 110s AbortSignal so this fetch times out cleanly before the 120s
  // platform limit fires — the caller gets a well-formed 504 rather than a
  // torn connection that the FE's axios catch renders as a generic network error.
  const response = await fetch(
    backendUrl(`/chat/sessions/${params.sessionId}/message`, request.nextUrl.search),
    {
      method: "POST",
      headers: await forwardedHeaders(request, { "Content-Type": "application/json" }),
      body: await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(110_000),
    }
  );

  const data = await response.text();
  return new NextResponse(data || null, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
