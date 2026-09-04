import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * DELETE /api/autopilot/history/{batchId}
 *   → BE DELETE /api/v1/autopilot/history/{batchId}
 *
 * FE Gap 434 / BE Gap 429: dismisses one sync run from the history list.
 * `batchId` is either a batch UUID or the literal `legacy` (the pre-Gap-427
 * bucket, same vocabulary as the sibling `/files` route). Hiding a run does not
 * delete its rows — duplicate detection still sees them.
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { batchId: string } }
) {
  return proxyJson(
    request,
    `/autopilot/history/${encodeURIComponent(params.batchId)}`
  );
}
