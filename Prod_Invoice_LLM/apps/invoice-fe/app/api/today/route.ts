// =============================================================================
// FILE: app/api/today/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:101).
//
// Backend: GET /api/v1/today
//   200  {state: "pre_onboarding", docs_seen, docs_required}
//        | {state: "active", position_lines, findings, summary,
//           input_requests, proposals, next_question}
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/today");
}
