import { NextRequest } from "next/server";
import { relayPayuCallback } from "../relay";

export const dynamic = "force-dynamic";

/**
 * Website path : POST /api/v1/billing/payu/failure   (furl)
 * BE path      : POST /api/v1/billing/payu/failure
 *
 * See ./success/route.ts and ../relay.ts.
 */
export async function POST(request: NextRequest) {
  return relayPayuCallback(request, "failure");
}
