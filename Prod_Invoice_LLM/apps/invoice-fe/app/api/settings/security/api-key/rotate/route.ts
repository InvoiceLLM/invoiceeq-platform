import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Gap 184 — API key rotation proxy.
 * FE path : /api/settings/security/api-key/rotate
 * BE path : /api/v1/settings/security/api-key/rotate
 *
 * The only response in the app that carries a raw API key. It is passed
 * straight through to the caller and never persisted client-side beyond the
 * component state that renders it once; the backend is Admin-gated (403
 * otherwise), so this route deliberately adds no gate of its own — the session
 * it forwards is what the backend judges.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/settings/security/api-key/rotate");
}
