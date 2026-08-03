import { NextRequest } from "next/server";
import { relayPayuCallback } from "../relay";

export const dynamic = "force-dynamic";

/**
 * Website path : POST /api/v1/billing/payu/success   (surl)
 * BE path      : POST /api/v1/billing/payu/success
 *
 * Path shape is identical to the backend's on purpose, so
 * routers/billing.py can build surl/furl from a single BACKEND_PUBLIC_URL
 * with no special-casing. See ./relay.ts for why this is unauthenticated
 * and why the redirect is relayed rather than followed.
 */
export async function POST(request: NextRequest) {
  return relayPayuCallback(request, "success");
}
