import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/billing/reactivate → BE POST /billing/reactivate (FE Gap 264 / BE Gap 264) */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/billing/reactivate");
}
