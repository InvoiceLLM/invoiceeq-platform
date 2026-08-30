import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 17 (FE Gap 323) — Plug & Play workflow config proxy route.
 * FE path : /api/settings/workflow
 * BE path : /api/v1/settings/workflow   (BE Feature 25 / Gap 336)
 *
 * Both verbs are Admin-only on the backend, including the GET — unlike
 * /settings/vendor-flow, which any role may read. The GET reports
 * `api_key_scope` (security configuration), so `_require_admin_for_workflow()`
 * gates it too; callers are expected to check the role before fetching rather
 * than to treat a 403 here as unexpected.
 *
 * `proxyJson` forwards the backend status and body untouched, which is what
 * lets the wizard show the backend's own 422 `detail` text when an output
 * destination that has not been built yet (email_summary / drive_archive) is
 * submitted. Nothing in this path reshapes an error body.
 */

/** GET /api/settings/workflow → BE GET /settings/workflow */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/settings/workflow");
}

/** PUT /api/settings/workflow → BE PUT /settings/workflow */
export async function PUT(request: NextRequest) {
  return proxyJson(request, "/settings/workflow");
}
