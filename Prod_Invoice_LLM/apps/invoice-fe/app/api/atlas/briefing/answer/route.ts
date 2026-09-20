// =============================================================================
// FILE: app/api/atlas/briefing/answer/route.ts
// FEATURE: FE Feature 24 task 24.2 (spec §2) — BE Feature 35 task 35.9's
//          `POST /api/v1/atlas/briefing/answer`.
//
// Plain `proxyJson`, the same shape as `app/api/atlas/memory/route.ts`, and for
// the same reason it matters there: the user's words pass through untouched in
// both directions, and this handler sets no provenance. The backend fixes the
// rule's source to `interview`; a client that could name its own provenance
// could label a lesson it invented as one the user gave.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/atlas/briefing/answer → BE POST /api/v1/atlas/briefing/answer (201). */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/atlas/briefing/answer");
}
