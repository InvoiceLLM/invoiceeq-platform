import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/from-invoice -> backend /trainer/sessions/from-invoice
 *
 * Feature 14 / BE Feature 18: the unified, alert-anchored session entry point.
 * Replaces both removed routes — `/sessions/global` (Global-scope rule creation
 * is gone) and `/sessions/from-production` (which could only ever open a
 * vendor's newest invoice). Body is `{invoice_id, session_mode?}`.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/trainer/sessions/from-invoice");
}
