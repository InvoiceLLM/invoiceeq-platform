import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 10 — Service Flow proxy route.
 * FE path : /api/settings/service-flow
 * BE path  : /api/v1/settings/vendor-flow  (internal name unchanged)
 */

/** GET /api/settings/service-flow → BE GET /settings/vendor-flow */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/settings/vendor-flow");
}

/** PUT /api/settings/service-flow → BE PUT /settings/vendor-flow */
export async function PUT(request: NextRequest) {
  return proxyJson(request, "/settings/vendor-flow");
}
