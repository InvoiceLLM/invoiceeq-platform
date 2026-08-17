import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/chat/rules/categories -> backend /chat/rules/categories
 *
 * The closed vocabulary a chat correction is picked from. Free text is never the
 * primary input in this lane: the category drives a deterministic template
 * (`services/chat_rules.py::render_chat_rule`), so the preview can show the
 * literal final rule text rather than a paraphrase of it.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/chat/rules/categories");
}
