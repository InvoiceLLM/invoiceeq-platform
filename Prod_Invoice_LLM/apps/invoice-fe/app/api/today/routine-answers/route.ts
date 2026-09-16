// =============================================================================
// FILE: app/api/today/routine-answers/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:483).
//
// Backend: GET /api/v1/today/routine-answers
//   200  {answers: {key: value}, contradictions: [key]}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/today/routine-answers");
}
