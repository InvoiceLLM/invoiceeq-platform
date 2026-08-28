import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/autopilot/config → BE GET /api/v1/autopilot/config */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/autopilot/config");
}

/** PUT /api/autopilot/config → BE PUT /api/v1/autopilot/config */
export async function PUT(request: NextRequest) {
  return proxyJson(request, "/autopilot/config");
}
