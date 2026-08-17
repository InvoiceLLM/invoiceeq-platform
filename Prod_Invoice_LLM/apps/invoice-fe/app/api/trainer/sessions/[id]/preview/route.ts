import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/{id}/preview -> backend equivalent.
 *
 * The preview-before-commit gate. Every correction path — tolerance, confidence
 * threshold, severity/message override, missed alert — goes through this one
 * endpoint before anything is written. Returns the structured interpretation of
 * each new rule, real historical impact (or an explicit "not computable", never
 * a fabricated zero), and a `previewToken` that `/commit` checks for drift.
 */
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/preview`);
}
