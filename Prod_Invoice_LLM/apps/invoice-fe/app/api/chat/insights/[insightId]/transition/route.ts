// =============================================================================
// FILE: app/api/chat/insights/[insightId]/transition/route.ts
// FEATURE: FE Feature 21 — Business Intelligence bubble (BE Feature 30 §8.6).
// REASON ADDED: same-origin proxy for POST /chat/insights/{id}/transition, matching every other
//   route under app/api/** rather than calling the backend from the browser.
//   Records the USER's bookkeeping about a finding — a note, or dismissing it.
//   Information only: the backend route reads and writes no `Invoice` row.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { insightId: string } }
) {
  return proxyJson(request, `/chat/insights/${params.insightId}/transition`);
}
