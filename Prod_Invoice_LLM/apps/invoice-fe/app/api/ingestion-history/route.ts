import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/ingestion-history → BE GET /api/v1/ingestion-history
 *
 * FE Gap 464. invoice-be's ingress is `external: false`, so the browser cannot
 * reach it directly and every call goes through a route handler. Same shape as
 * `app/api/autopilot/history/route.ts` — `proxyJson` + `force-dynamic` — so
 * auth-header forwarding stays in one place.
 *
 * The query string (`page`, `page_size`, `trigger`, `flow_direction`,
 * `archived`) is forwarded verbatim, so the filters and the `X-Total-Count`
 * header work without this file knowing what the filters are.
 *
 * Tenant scoping is the BACKEND's and is not re-implemented here:
 * `routers/ingestion_history.py` resolves the tenant from the auth context and
 * carries it in the WHERE clause of every query. A proxy that filtered would be
 * a second, weaker copy of that rule.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/ingestion-history");
}
