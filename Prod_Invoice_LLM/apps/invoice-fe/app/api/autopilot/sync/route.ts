import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/autopilot/sync → BE POST /api/v1/autopilot/sync */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/autopilot/sync");
}
