import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/autopilot/history → BE GET /api/v1/autopilot/history */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/autopilot/history");
}
