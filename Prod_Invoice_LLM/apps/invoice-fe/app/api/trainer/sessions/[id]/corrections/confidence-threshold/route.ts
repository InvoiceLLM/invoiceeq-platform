import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/{id}/corrections/confidence-threshold -> backend equivalent.
 *
 * Correction #2: "this low-confidence alert was unnecessary". Body
 * `{threshold, field?}`.
 *
 * Its own route rather than a variant of the tolerance one, because
 * `low_confidence_field` is produced by `verify_field_confidence(threshold=...)`
 * — a different parameter on a different function from the tolerance checks.
 * Sharing one form would have shipped a control whose numbers silently did
 * nothing on half the alert types it was offered for.
 */
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/corrections/confidence-threshold`);
}
