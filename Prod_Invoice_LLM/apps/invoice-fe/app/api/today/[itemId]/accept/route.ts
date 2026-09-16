// =============================================================================
// FILE: app/api/today/[itemId]/accept/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:373).
//
// Backend: POST /api/v1/today/{id}/accept
//   200  {ok, rule_id, rule_text} | {ok: false, error}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
//
// `[itemId]`, not `[proposalId]`: the backend names this segment
// `proposal_id`, but Next.js requires one dynamic segment name per level
// and `[itemId]` already owns this one (open / dismiss / scenario / confirm).
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { itemId: string } }
) {
  return proxyJson(request, `/today/${encodeURIComponent(params.itemId)}/accept`);
}
