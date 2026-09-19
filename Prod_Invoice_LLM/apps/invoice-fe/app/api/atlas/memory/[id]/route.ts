// =============================================================================
// FILE: app/api/atlas/memory/[id]/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.10 (§7.2). FE Gap 700.
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as
// `app/api/atlas/lines/[id]/dismiss/route.ts`, including its rule: this handler
// decides nothing. Tenant scoping is the backend's — `routers/atlas.py` keys
// every rule on `TenantContext.tenant_id`, and answers 404 (never 403) on
// another tenant's id, because a 403 confirms the row exists. There is
// deliberately no validation here: a second copy of a rule is the copy that
// drifts.
//
// DELETE IS A HARD DELETE AND THIS PATH DOES NOT SOFTEN IT. The backend removes
// the row; there is no `deleted_at`, no archive and nothing here that hides a
// row the server still holds. §7.2's argument is the reason — a wrong lesson
// that cannot be found haunts the system forever, and a retained-but-hidden
// rule is precisely one that cannot be found.
//
// THE 204 PASSES THROUGH CORRECTLY because of FE Gap 177's fix inside
// `proxyJson` (a null body for null-body statuses); this route relies on it
// rather than special-casing the status here.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** PATCH /api/atlas/memory/{id} → BE PATCH /api/v1/atlas/memory/{id} */
export async function PATCH(
  request: NextRequest,
  // Next 14 route-handler shape, matching app/api/atlas/lines/[id]/dismiss.
  { params }: { params: { id: string } }
) {
  // hardcode-ok: this app's own backend route path; `id` is a rule UUID, never a figure
  return proxyJson(request, `/atlas/memory/${encodeURIComponent(params.id)}`);
}

/** DELETE /api/atlas/memory/{id} → BE DELETE /api/v1/atlas/memory/{id} */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  // hardcode-ok: this app's own backend route path; `id` is a rule UUID, never a figure
  return proxyJson(request, `/atlas/memory/${encodeURIComponent(params.id)}`);
}
