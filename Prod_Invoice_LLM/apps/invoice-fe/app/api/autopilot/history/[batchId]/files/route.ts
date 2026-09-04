import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/autopilot/history/{batchId}/files
 *   → BE GET /api/v1/autopilot/history/{batchId}/files
 *
 * FE Gap 428 / BE Gap 427: drill-down for one Autopilot sync run. `batchId` is
 * either a batch UUID or the literal `legacy`, which the backend maps to the
 * pre-Gap-427 rows that carry no `batch_id`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: { batchId: string } }
) {
  return proxyJson(
    request,
    `/autopilot/history/${encodeURIComponent(params.batchId)}/files`
  );
}
