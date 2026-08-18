import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/support/chat
 * BE path : /api/v1/support/chat
 *
 * Proxies conversational AI troubleshooting queries from SAGE Assistant
 * in the Help Center to the backend support agent.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/support/chat");
}
