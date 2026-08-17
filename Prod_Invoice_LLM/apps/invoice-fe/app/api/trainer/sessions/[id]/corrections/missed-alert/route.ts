import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/{id}/corrections/missed-alert -> backend equivalent.
 *
 * Correction #4: "I expected an alert here and got none". Body
 * `{alert_type, field, context?}`.
 *
 * `alert_type` and `field` are structured picks and are the **primary** input;
 * `context` is optional prose the backend passes to the LLM as secondary colour
 * only. This is the one correction path that involves an LLM at all, and it
 * fails closed — on a drafting failure the backend 502s and stages nothing,
 * rather than promoting the raw input into a rule.
 */
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/corrections/missed-alert`);
}
