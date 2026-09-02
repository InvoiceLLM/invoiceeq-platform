// =============================================================================
// FILE: app/api/documents/route.ts
// FEATURE: FE surface of BE Feature 27 E10 / G14, task R5(c).
//
// REASON ADDED: E10 sends every non-INVOICE-family document to the `documents`
//   table and DELETES the placeholder `invoice` row in the same transaction. The
//   product consequence, which E10 states openly, is that a classified delivery
//   note vanishes from the ingestion status table the moment classification
//   succeeds -- it is no longer an invoice, and nothing else listed it.
//
//   That is why §2A/N1 calls G11 a ROLLOUT gate rather than a build gate:
//   ENABLE_GENERIC_EXTRACTION must not be turned on in any deployment a user can
//   see until a classified document is visible SOMEWHERE. `GET /documents`
//   (G14) has existed since Gap 381 with no consumer; this is the consumer.
//
// invoice-be's ingress is `external: false`, so the browser cannot reach it
//   directly and every call goes through a route handler. Same shape as
//   `app/api/invoices/route.ts` -- `proxyJson` + `force-dynamic` -- rather than a
//   hand-rolled fetch, so auth-header forwarding stays in one place.
//
// Tenant scoping is the BACKEND's and is not re-implemented here:
//   `routers/documents.py` resolves the tenant from the auth context and
//   `_require_owned_document()` answers 404 (never 403) on a cross-tenant id.
//   A proxy that filtered would be a second, weaker copy of that rule.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  // The query string is forwarded verbatim, so `doc_type` and `batch_id`
  // filtering and the `X-Total-Count` header work without this file knowing what
  // the filters are.
  return proxyJson(request, "/documents");
}
