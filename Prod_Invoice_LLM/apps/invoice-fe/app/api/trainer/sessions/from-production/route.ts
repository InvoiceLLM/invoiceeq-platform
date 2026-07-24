import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// POST /api/trainer/sessions/from-production?vendor_name=... -> backend equivalent.
// No body; the vendor_name query string is preserved by proxyJson.
export async function POST(request: NextRequest) {
  return proxyJson(request, "/trainer/sessions/from-production");
}
