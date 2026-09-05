import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/ingestion-history/{runId}/archive
 *   → BE POST /api/v1/ingestion-history/{runId}/archive
 *
 * FE Gap 464: archives one run from the history log. POST, not DELETE, and
 * "Archive", not "Delete", deliberately and in one word only — the founder's
 * ruling is that two words for one behaviour is what makes a user believe one
 * of them removes the invoice. Nothing about the invoice changes; real invoice
 * deletion lives on the Audit Queue, where the consequence is visible.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: { runId: string } }
) {
  return proxyJson(
    request,
    `/ingestion-history/${encodeURIComponent(params.runId)}/archive`
  );
}
