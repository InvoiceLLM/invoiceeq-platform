import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/chat/rules/commit -> backend /chat/rules/commit
 *
 * Persists a chat-behaviour rule. The `preview_token` is **required** by the
 * backend (a commit without one is a 400, and a stale one is a 409), so there is
 * no path from a thumbs-down to a saved rule that skips the confirmation screen.
 *
 * Gated on `can_train` server-side: a `TenantChatRule` changes how every future
 * answer for the whole workspace is scoped, which is a training action even
 * though it is reached from the Chat UI.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/chat/rules/commit");
}
