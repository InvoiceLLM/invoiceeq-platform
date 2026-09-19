// =============================================================================
// FILE: app/api/atlas/lines/[id]/act/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.7 (D50, D51), the act click.
//
// invoice-be's ingress is `external: false`, so the browser cannot reach it
// directly; every call goes through a route handler. Same `proxyJson` +
// `force-dynamic` shape as the dismiss handler beside it, so auth-header
// forwarding stays in one place.
//
// THIS HANDLER DECIDES NOTHING, AND THAT IS LOAD-BEARING HERE MORE THAN
// ANYWHERE ELSE IN THIS APP. This is the one route that causes a write to a
// customer's invoice. Every rule that governs it is the backend's:
//
//   * which kinds may be performed at all (D50/D51 — two, and the rest are
//     refused 409 by `services/atlas_actions.py`);
//   * whether this caller may act, which is a SEPARATE decision from whether
//     they may see (BE 34.7b) and is made against the grants resolved from the
//     forwarded credential, not from anything in this URL;
//   * what payload the underlying `PUT /audit/resolve/{invoice_id}` receives —
//     rebuilt from a whitelist on the backend, never forwarded, so a field this
//     proxy passed along could not turn a resolve into a standing rule.
//
// A check added here would be a second copy of one of those rules, and the copy
// is the one that drifts. There is deliberately no validation in this file.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/atlas/lines/{id}/act → BE POST /api/v1/atlas/lines/{id}/act */
export async function POST(
  request: NextRequest,
  // Next 14 route-handler shape, matching app/api/chat/sessions/[sessionId].
  { params }: { params: { id: string } }
) {
  // hardcode-ok: this app's own backend route path; `id` is a deterministic
  // recommendation id (`audit-approve-<invoice id>`), never a figure or money
  return proxyJson(request, `/atlas/lines/${encodeURIComponent(params.id)}/act`); // hardcode-ok: this app's own backend route path; the interpolated value is a recommendation id, not a figure
}
