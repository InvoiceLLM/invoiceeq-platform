import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/ingestion-history/{runId}/unarchive
 *   → BE POST /api/v1/ingestion-history/{runId}/unarchive
 *
 * FE Gap 464: restores an archived run to the live list — the exact inverse of
 * /archive, and the reason archiving is safe to offer at all.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: { runId: string } }
) {
  return proxyJson(
    request,
    `/ingestion-history/${encodeURIComponent(params.runId)}/unarchive`
  );
}
