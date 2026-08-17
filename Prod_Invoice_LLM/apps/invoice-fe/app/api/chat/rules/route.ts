import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/chat/rules -> backend /chat/rules
 *
 * The tenant's committed chat-behaviour rules (`TenantChatRule`), so they can be
 * reviewed. These are a separate store from `ExtractionTemplate.rules` by
 * design — a chat rule is about how the answering agent scopes a question, and
 * has nothing to teach the extraction pipeline.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/chat/rules");
}
