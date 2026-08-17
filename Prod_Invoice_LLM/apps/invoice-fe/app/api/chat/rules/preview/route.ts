import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/chat/rules/preview -> backend /chat/rules/preview
 *
 * Same preview-before-commit principle as the extraction lane: a thumbs-down
 * never silently saves a rule. Returns the rule in the exact terms it will be
 * injected as, plus a `previewToken` that `/commit` requires.
 *
 * Deliberately NOT gated on `can_train` server-side — anyone who can see a bad
 * answer should be able to report it and see what would be proposed. Only the
 * commit is gated.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/chat/rules/preview");
}
