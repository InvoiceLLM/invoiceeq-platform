import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/billing/usage → BE GET /billing/usage
 *
 * Gap 143: the Subscriptions & Billing usage bar had no endpoint of its own and
 * counted invoice rows instead, mis-reading `GET /invoices`'s `X-Total-Count`
 * header as a JSON body. This proxies the real counter the ingestion gate
 * enforces against.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/billing/usage");
}
