// =============================================================================
// FILE: app/api/atlas/orientation/route.ts
// FEATURE: FE Feature 23 task 9 — BE Feature 34 task 34.12 (§7.1, D24, D25).
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as the rest of this feature.
//
// THE CONTENT IS THE BACKEND'S, INCLUDING THE PART THAT IS A PROMISE. §7.1's
// third part — "right now I do not know your vendors… in a month I will" — is a
// commitment about what the product will be able to do. It is served from a
// fixed table on the backend precisely so it cannot vary per visit, and this
// handler must never compose, shorten or localise it.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/atlas/orientation → BE GET /api/v1/atlas/orientation */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/atlas/orientation");
}
