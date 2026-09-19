// =============================================================================
// FILE: app/api/atlas/lines/route.ts
// FEATURE: FE Feature 23 (the work screen) — the read the whole screen is.
//
// invoice-be's ingress is `external: false`, so the browser cannot reach it
// directly; every call goes through a route handler. Same shape as
// `app/api/documents/route.ts` — `proxyJson` + `force-dynamic` — so auth-header
// forwarding stays in one place.
//
// TENANT SCOPING AND CAPABILITY FILTERING ARE THE BACKEND'S, and are not
// re-implemented here. `routers/atlas.py` resolves the grants from the auth
// context and `visible_to()` DROPS the lines the caller may not act on
// (BE §2.1, "absent, not disabled"). A proxy that filtered would be a second,
// weaker copy of that rule — and the weaker copy is the one that eventually
// disagrees.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/atlas/lines → BE GET /api/v1/atlas/lines */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/atlas/lines");
}
