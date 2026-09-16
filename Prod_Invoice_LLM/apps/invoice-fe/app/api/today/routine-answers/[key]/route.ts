// =============================================================================
// FILE: app/api/today/routine-answers/[key]/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:496).
//
// Backend: PATCH /api/v1/today/routine-answers/{key}
//   body  {value}
//   200   {ok, key, value}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function PATCH(
  request: NextRequest,
  { params }: { params: { key: string } }
) {
  return proxyJson(request, `/today/routine-answers/${encodeURIComponent(params.key)}`);
}
