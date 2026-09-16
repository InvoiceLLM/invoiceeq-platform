// =============================================================================
// FILE: app/api/today/questionnaire/answer/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:449).
//
// Backend: POST /api/v1/today/questionnaire/answer
//   body  {key, value, path}
//   200   {ok, saved_key, has_next, next_question}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyJson(request, "/today/questionnaire/answer");
}
