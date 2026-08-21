import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/autopilot/history → BE GET /autopilot/history
 *
 * FE Gap 278 -- see app/api/autopilot/config/route.ts for the full write-up.
 *
 * `proxyJson` forwards `request.nextUrl.search` untouched, so the
 * `?page=&page_size=` pagination AutopilotHistoryTable.tsx sends needs no
 * special handling here.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/autopilot/history");
}
