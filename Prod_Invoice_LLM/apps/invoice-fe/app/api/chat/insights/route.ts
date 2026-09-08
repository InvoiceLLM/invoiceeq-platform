// =============================================================================
// FILE: app/api/chat/insights/route.ts
// FEATURE: FE Feature 21 — Business Intelligence bubble (BE Feature 30 §8.6).
// REASON ADDED: same-origin proxy for GET /chat/insights, matching every other
//   route under app/api/** rather than calling the backend from the browser.
//   Read-only: the list of findings for this tenant. Nothing here changes an
//   invoice (BE Gap 492).
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  // `proxyJson` already forwards `request.nextUrl.search`, so `status`,
  // `attachment_id` and `limit` reach the backend untouched.
  return proxyJson(request, "/chat/insights");
}
