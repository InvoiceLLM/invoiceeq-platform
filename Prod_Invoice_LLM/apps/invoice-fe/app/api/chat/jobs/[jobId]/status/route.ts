// =============================================================================
// FILE: app/api/chat/jobs/[jobId]/status/route.ts
// FEATURE: Gap 280 — Queue-based Chat Status Polling Proxy
// =============================================================================

import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: { jobId: string } }
) {
  return proxyJson(request, `/chat/jobs/${params.jobId}/status`);
}
