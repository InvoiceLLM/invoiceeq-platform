import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/trainer/alert-types -> backend /trainer/alert-types
 *
 * The alert-type registry (`utils/alert_registry.py`). Drives the "which alert
 * did you expect here?" picker and tells the correction UI which form each type
 * supports, so the FE never hardcodes a second copy of that mapping.
 * `proxyJson` preserves `?flaggable_only=true`.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/trainer/alert-types");
}
