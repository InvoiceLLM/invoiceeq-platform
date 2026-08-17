import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * DELETE /api/chat/rules/{ruleId} -> backend /chat/rules/{rule_id}
 *
 * Removes a committed chat-behaviour rule. Same `can_train` permission as
 * creating one.
 *
 * The backend answers 204; `proxyJson` already handles null-body statuses
 * correctly (FE Gap 177), so this needs no special-casing here.
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { ruleId: string } }
) {
  return proxyJson(request, `/chat/rules/${params.ruleId}`);
}
