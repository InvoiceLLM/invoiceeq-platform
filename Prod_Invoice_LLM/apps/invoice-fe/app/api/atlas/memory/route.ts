// =============================================================================
// FILE: app/api/atlas/memory/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.10 (§7.2, D31, D40, D12).
//          FE Gap 700.
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as the rest of this feature.
//
// THE USER'S WORDS PASS THROUGH UNTOUCHED, IN BOTH DIRECTIONS. §7.2's promise is
// that a lesson is held "in plain language" — the language it was given in. This
// handler does not trim, capitalise, template or summarise a rule on the way in
// or on the way out.
//
// THIS HANDLER SETS NO PROVENANCE. `source` is the backend's (`told` for a POST
// here), and deliberately not a field this side can supply: a client that could
// name its own provenance could label a lesson it invented as one the user gave,
// and provenance is what makes a wrong lesson judgeable.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/atlas/memory → BE GET /api/v1/atlas/memory */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/atlas/memory");
}

/** POST /api/atlas/memory → BE POST /api/v1/atlas/memory */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/atlas/memory");
}
