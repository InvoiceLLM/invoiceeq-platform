// =============================================================================
// FILE: app/api/today/run/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33
//          (apps/invoice-be/routers/today.py:517).
//
// Backend: POST /api/v1/today/run
//   200  {ok, job_id, status: "enqueued", cooldown_seconds}
//   403  not Admin
//   429  {detail, retry_after_seconds} — the cooldown; RunNowButton renders it inline
//
// proxyJson forwards status and body verbatim: Today renders backend errors
// on the line that caused them, so they must not collapse into a generic 500.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyJson(request, "/today/run");
}
