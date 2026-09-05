import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/ingestion-history/archive-all
 *   → BE POST /api/v1/ingestion-history/archive-all
 *
 * FE Gap 464: archives every currently-visible run, across all three sources
 * (manual/email/connector runs, Autopilot runs, rejected inbound mails). An
 * "archive all" that quietly skipped a source would leave the list non-empty
 * the instant after the user emptied it.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/ingestion-history/archive-all");
}
