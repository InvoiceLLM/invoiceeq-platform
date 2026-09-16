// =============================================================================
// FILE: app/api/today/questionnaire/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:426).
//
// Backend: GET /api/v1/today/questionnaire
//   query  ?path=setup|ingest (forwarded by proxyJson)
//   200    {completed: true, question: null} | {completed: false, question}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/today/questionnaire");
}
