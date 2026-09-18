// =============================================================================
// FILE: app/api/atlas/actions/kinds/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.7d.
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as the rest of this feature.
//
// WHY THIS ROUTE EXISTS AT ALL: so that "which actions can this product actually
// perform" is a question the browser asks the backend, rather than a constant
// this app keeps in step by hand. `PERFORMABLE_ACTION_KINDS` shipped empty in
// Slice B as a deliberate honesty mechanism — a button is never enabled ahead of
// its endpoint — and the strongest form of that rule is that this side holds no
// list of its own to fall out of date.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/atlas/actions/kinds → BE GET /api/v1/atlas/actions/kinds */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/atlas/actions/kinds");
}
