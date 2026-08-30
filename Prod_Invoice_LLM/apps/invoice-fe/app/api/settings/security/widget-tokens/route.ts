import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 17 (FE Gap 325) — embedded chat widget tokens.
 * FE path : /api/settings/security/widget-tokens
 * BE path : /api/v1/settings/security/widget-tokens   (BE Feature 25 / Gap 341)
 *
 * All three verbs are Admin-only on the backend, including the GET — the list
 * of live credentials and their `allowed_origins` is security configuration,
 * not something a Trainer needs. Callers check the role before fetching rather
 * than treating the 403 as unexpected, the same way /api/settings/workflow does.
 *
 * The POST response is the only place in this app that carries a raw widget
 * token; it is passed straight through and never persisted anywhere on this
 * side. `proxyJson` forwards status and body untouched, which is what lets the
 * backend's own 409 (per-tenant token cap) and 422 (unusable origin) text reach
 * the UI verbatim.
 */

/** GET → this workspace's un-revoked widget tokens, metadata only. */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/settings/security/widget-tokens");
}

/** POST → issue a widget token. Shown once, in this response only. */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/settings/security/widget-tokens");
}
