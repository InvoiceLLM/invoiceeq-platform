// =============================================================================
// FILE: app/api/documents/[id]/route.ts
// FEATURE: BE Gap 725 / 733 — read ONE document through the app.
//
// REASON ADDED: `GET /documents` was proxied from the day the list screen
//   needed it, but `GET /documents/{id}` never was. That was invisible while the
//   only caller was a browser page that already had the row in hand from the
//   list. BE Gap 725 opened both backend endpoints to an API key, and an
//   integration does the opposite of the screen: it lists ids and then fetches
//   each one. Without this file that second call reaches no route handler and
//   Next answers with its own 404 HTML page — a caller would reasonably read
//   that as "the document does not exist" when the document is right there.
//
//   invoice-be's ingress is `external: false`, so nothing outside the cluster
//   can call the backend directly; a missing route handler is a missing
//   endpoint, not merely a missing shortcut.
//
// DELETE is deliberately NOT proxied here. `routers/documents.py` keeps the
//   Clerk-only dependency on its delete handler (a key reads, it does not
//   destroy), so a DELETE arriving here would travel to the backend purely to be
//   refused. The document delete the app itself performs goes through the
//   Documents screen, which holds a session.
//
// Tenant scoping is the BACKEND's and is not re-implemented here:
//   `_require_owned_document()` answers 404 — never 403 — on another tenant's
//   id, so this handler must not try to be a second, weaker copy of that rule.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/documents/{id} → BE GET /documents/{id} */
export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  return proxyJson(request, `/documents/${params.id}`);
}
