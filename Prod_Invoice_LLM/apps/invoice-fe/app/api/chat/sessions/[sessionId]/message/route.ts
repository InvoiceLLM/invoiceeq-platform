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
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

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
  return proxyJson(request, `/chat/sessions/${params.sessionId}/message`);
}
