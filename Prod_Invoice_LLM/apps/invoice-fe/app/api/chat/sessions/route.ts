// =============================================================================
// FILE: app/api/chat/sessions/route.ts
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: Next.js cannot call the FastAPI backend directly from the
//   browser — the backend URL (BACKEND_API_URL) is a private server-side env
//   variable and is unreachable from client code.  This Route Handler runs
//   server-side and acts as a secure same-origin proxy:
//     Browser → /api/chat/sessions (this file) → BACKEND_API_URL/api/v1/chat/sessions
//   proxyJson() from lib/backendProxy.ts forwards the method, body, query
//   string, and the Authorization header from the incoming Clerk JWT.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// GET /api/chat/sessions
// WHY: Returns the list of conversation threads for the sidebar panel.
//   Called by useChatSession.fetchSessions() on component mount.
export async function GET(request: NextRequest) {
  return proxyJson(request, "/chat/sessions");
}

// POST /api/chat/sessions
// WHY: Creates a new conversation session on the backend (generates a UUID,
//   stores tenant_id from the JWT).  Called by useChatSession.createSession()
//   when the user clicks "+ New Chat".
export async function POST(request: NextRequest) {
  return proxyJson(request, "/chat/sessions");
}
