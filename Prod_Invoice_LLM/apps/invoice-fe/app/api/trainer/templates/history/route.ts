import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// GET /api/trainer/templates/history?scope=&vendor_name= -> backend equivalent.
// The scope / vendor_name query string is preserved by proxyJson.
export async function GET(request: NextRequest) {
  return proxyJson(request, "/trainer/templates/history");
}
