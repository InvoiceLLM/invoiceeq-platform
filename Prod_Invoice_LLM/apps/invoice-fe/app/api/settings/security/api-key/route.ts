import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Gap 184 — API key status proxy.
 * FE path : /api/settings/security/api-key
 * BE path : /api/v1/settings/security/api-key
 *
 * Metadata only (prefix, rotated_at, last_used_at, can_rotate). The backend
 * never puts the raw key in this response — it exists in exactly one response
 * in the whole API, the rotate call in ./rotate/route.ts.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/settings/security/api-key");
}
