// =============================================================================
// FILE: app/api/today/[itemId]/dismiss/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:274).
//
// Backend: POST /api/v1/today/{id}/dismiss
//   200  {ok, item_id, dismissed: true} — also feeds learn()
//   400  invalid UUID · 404 not this tenant's item
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { itemId: string } }
) {
  return proxyJson(request, `/today/${encodeURIComponent(params.itemId)}/dismiss`);
}
