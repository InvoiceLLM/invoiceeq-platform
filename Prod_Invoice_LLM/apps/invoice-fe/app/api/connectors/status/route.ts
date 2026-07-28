import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/connectors/status → BE GET /connectors/status */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/connectors/status");
}
