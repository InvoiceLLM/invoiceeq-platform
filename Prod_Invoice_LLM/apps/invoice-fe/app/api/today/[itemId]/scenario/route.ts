// =============================================================================
// FILE: app/api/today/[itemId]/scenario/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:309).
//
// Backend: POST /api/v1/today/{id}/scenario
//   body  {change, horizon_days}
//   200   {ok, currencies, cash_position_by_currency, runway_days_by_currency,
//          certain_summary, tiers_summary}
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
  return proxyJson(request, `/today/${encodeURIComponent(params.itemId)}/scenario`);
}
