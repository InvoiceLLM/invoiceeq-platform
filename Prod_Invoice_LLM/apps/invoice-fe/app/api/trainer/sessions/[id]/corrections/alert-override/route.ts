import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/{id}/corrections/alert-override -> backend equivalent.
 *
 * Correction #3: the alert is right to fire, but its severity or wording is
 * wrong. Body `{alert_type, field?, severity?, message?}` — at least one of
 * severity/message is required (an empty override would do nothing, and the
 * backend 400s on it).
 *
 * This never changes *whether* an alert fires. Suppression is the
 * tolerance/threshold path's job; conflating "call this a warning" with "stop
 * telling me" is how real findings get silently lost.
 */
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/corrections/alert-override`);
}
