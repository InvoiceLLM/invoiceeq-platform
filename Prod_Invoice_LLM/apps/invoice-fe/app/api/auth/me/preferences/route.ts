// =============================================================================
// FILE: app/api/auth/me/preferences/route.ts
// FEATURE: FE Feature 22 Task 22.0 — proxy for BE Feature 33 Task 33.39
//          (apps/invoice-be/routers/auth.py:421 GET, :448 PATCH).
//
// Backend: GET   /auth/me/preferences
//          PATCH /auth/me/preferences   body {layout?, first_run_seen?, tour_seen?,
//                                             questionnaire_progress?}
//   200  {layout: "surfaces", first_run_seen: false, tour_seen: false,
//         questionnaire_progress: null}  — defaults merged with what is stored
//   400  unknown key (PATCH) · 404 user record not found (PATCH)
//
// UNPREFIXED, like app/api/auth/me/route.ts: auth.router is mounted without
// /api/v1 (main.py:180), and proxyJson always appends it. `backendRootUrl`
// exists for exactly this case; `forwardedHeaders` is reused rather than
// re-implementing the Authorization / X-API-Key precedence a third time.
//
// Tasks 22.14 (`first_run_seen`) and 22.21 (`layout`) persist here, NOT in
// localStorage — the preference is per user and must survive a device change.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { backendRootUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

async function proxyPreferences(request: NextRequest): Promise<NextResponse> {
  const hasBody = request.method !== "GET";
  const response = await fetch(backendRootUrl("/auth/me/preferences"), {
    method: request.method,
    headers: await forwardedHeaders(request, { "Content-Type": "application/json" }),
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data === "" ? null : data, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}

export async function GET(request: NextRequest) {
  return proxyPreferences(request);
}

export async function PATCH(request: NextRequest) {
  return proxyPreferences(request);
}
