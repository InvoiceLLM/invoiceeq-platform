// =============================================================================
// FILE: app/api/today/[itemId]/confirm/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:328).
//
// Backend: POST /api/v1/today/{id}/confirm
//   200  {ok, result}
//   403  role not allowed — ActionLine renders this on the line itself
//   500  action execution failed
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
  return proxyJson(request, `/today/${encodeURIComponent(params.itemId)}/confirm`);
}
