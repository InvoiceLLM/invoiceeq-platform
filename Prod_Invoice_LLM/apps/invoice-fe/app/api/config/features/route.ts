// =============================================================================
// FILE: app/api/config/features/route.ts
// FEATURE: FE side of BE Feature 27 task R5(a) — the flag-exposure mechanism.
//
// REASON ADDED: §4 requires the DropZone accept-list widening be gated on
//   `ENABLE_GENERIC_EXTRACTION` "surfaced via the existing config/feature
//   endpoint, not hardcoded". FE Gap 378 recorded that no such endpoint
//   existed, which is what blocked the widening — it was never FE work.
//
// invoice-be's ingress is `external: false`, so the browser cannot reach it
//   directly. Same `proxyJson` + `force-dynamic` shape as every other route
//   handler here, so auth-header forwarding stays in one place.
//
// NOT CACHED AT THIS LAYER, deliberately. `force-dynamic` matches the rest of
//   the app, and the caching the ruling asks for is a BOOT-TIME cache in the
//   browser (`lib/featureFlags.ts` holds one in-flight promise for the page's
//   lifetime), not an HTTP cache here. Caching at the edge would make a flag
//   flip take effect at an unpredictable time, which is the opposite of what a
//   kill-switch is for.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/config/features");
}
