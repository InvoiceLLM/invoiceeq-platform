import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/autopilot/history → BE GET /api/v1/autopilot/history */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/autopilot/history");
}

/**
 * DELETE /api/autopilot/history → BE DELETE /api/v1/autopilot/history
 *
 * FE Gap 434 / BE Gap 429: "Clear history" — hides every run from this list.
 * The rows stay in the database, so duplicate detection is unaffected.
 */
export async function DELETE(request: NextRequest) {
  return proxyJson(request, "/autopilot/history");
}
