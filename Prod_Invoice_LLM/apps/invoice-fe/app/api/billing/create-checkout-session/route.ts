import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/billing/create-checkout-session → BE POST /billing/create-checkout-session */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/billing/create-checkout-session");
}
