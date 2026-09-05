import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/ingestion-history/{runId}/files
 *   → BE GET /api/v1/ingestion-history/{runId}/files
 *
 * FE Gap 464: the expand payload. This is the ONLY call that fetches the heavy
 * half — extracted fields, alerts, line items, doc attributes — and it is made
 * only when a row is expanded. The list itself stays a log.
 *
 * `runId` is a batch UUID, or `autopilot:<uuid>` / `email:<uuid>` for the two
 * read-through sources. It is encoded rather than interpolated raw so the colon
 * survives the hop.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: { runId: string } }
) {
  return proxyJson(
    request,
    `/ingestion-history/${encodeURIComponent(params.runId)}/files`
  );
}
