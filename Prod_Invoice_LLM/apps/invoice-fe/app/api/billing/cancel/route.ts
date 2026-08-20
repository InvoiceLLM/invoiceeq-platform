import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/billing/cancel → BE POST /billing/cancel (FE Gap 264 / BE Gap 264) */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/billing/cancel");
}
