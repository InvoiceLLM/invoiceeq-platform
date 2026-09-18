// =============================================================================
// FILE: app/api/atlas/actions/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.7c (§5.3). FE Gap 701.
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as the rest of this feature.
//
// WHY THIS ROUTE EXISTS: §5.3 lists "never writes silently: every write is
// visible, attributed and timestamped — what ATLAS did is a real list" as a
// BOUNDARY, not a feature. The list has existed since Slice C and could be
// reached only with `curl`, which is not visible in the sense that sentence
// means. This handler is the difference.
//
// NOTHING IS FILTERED HERE. The backend answers tenant-wide and includes
// refusals; a route handler that dropped the failures would turn a record into a
// highlight reel.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/atlas/actions → BE GET /api/v1/atlas/actions */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/atlas/actions");
}
