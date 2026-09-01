import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE Gap 358 — API key verify proxy. Did not exist before this gap, which is
 * why an external caller's inv_live_ key 404'd here even after the Clerk
 * middleware fix in middleware.ts.
 * FE path : /api/settings/security/api-key/verify
 * BE path : /api/v1/settings/security/api-key/verify
 *
 * The one BE route a bare API key could already reach before Gap 358 —
 * confirmed live via `az containerapp exec` directly against invoice-be,
 * bypassing this app entirely. This route is what makes that same call
 * reachable through the real public path.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/settings/security/api-key/verify");
}
