// =============================================================================
// FILE: app/api/atlas/lines/[id]/dismiss/route.ts
// FEATURE: FE Feature 23 — D49, the dismiss click.
//
// invoice-be's ingress is `external: false`, so the browser cannot reach it
// directly; every call goes through a route handler. Same `proxyJson` +
// `force-dynamic` shape as `app/api/atlas/lines/route.ts`, so auth-header
// forwarding stays in one place.
//
// THIS HANDLER DECIDES NOTHING. Tenant and user scoping are the backend's —
// `routers/atlas.py` keys the dismissal on `TenantContext.tenant_id` +
// `.user_id`, both resolved from the forwarded credential — so the id in this
// URL cannot be used to dismiss on someone else's behalf. There is deliberately
// no validation here: a second copy of a rule is the copy that drifts.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/atlas/lines/{id}/dismiss → BE POST /api/v1/atlas/lines/{id}/dismiss */
export async function POST(
  request: NextRequest,
  // Next 14 route-handler shape, matching app/api/chat/sessions/[sessionId].
  { params }: { params: { id: string } }
) {
  // hardcode-ok: this app's own backend route path; `id` is a deterministic
  // recommendation id (`audit-approve-<invoice id>`), never a figure or money
  return proxyJson(request, `/atlas/lines/${encodeURIComponent(params.id)}/dismiss`);
}
