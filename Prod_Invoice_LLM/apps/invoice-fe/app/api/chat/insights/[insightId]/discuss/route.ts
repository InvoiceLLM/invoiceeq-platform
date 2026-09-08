// =============================================================================
// FILE: app/api/chat/insights/[insightId]/discuss/route.ts
// FEATURE: FE Feature 21 — Business Intelligence bubble (BE Feature 30 §8.6).
// REASON ADDED: same-origin proxy for GET /chat/insights/{id}/discuss, matching every other
//   route under app/api/** rather than calling the backend from the browser.
//   A READ that returns seed text for the composer. It never sends a turn —
//   putting words in the user's mouth is the thing this endpoint avoids.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: { insightId: string } }
) {
  return proxyJson(request, `/chat/insights/${params.insightId}/discuss`);
}
