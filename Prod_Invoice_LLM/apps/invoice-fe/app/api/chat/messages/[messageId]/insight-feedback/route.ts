// =============================================================================
// FILE: app/api/chat/messages/[messageId]/insight-feedback/route.ts
// FEATURE: FE Feature 21 — Business Intelligence bubble (BE Feature 30 §8.6).
// REASON ADDED: same-origin proxy for POST /chat/messages/{id}/insight-feedback, matching every other
//   route under app/api/** rather than calling the backend from the browser.
//   Thumbs on ONE finding of a bubble. Distinct from the neighbouring
//   `feedback` route, which votes on the whole answer (Gap 54).
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { messageId: string } }
) {
  return proxyJson(request, `/chat/messages/${params.messageId}/insight-feedback`);
}
