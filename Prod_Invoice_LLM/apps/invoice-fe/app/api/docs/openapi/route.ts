import { NextRequest, NextResponse } from "next/server";
import { backendRootUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Gap 184 (Docs Hub) — serves the backend's OpenAPI document to the in-app
 * Swagger UI.
 *
 * Uses `backendRootUrl`, not `backendUrl`: FastAPI publishes `/openapi.json`
 * (and `/docs`) at the service root, outside the `/api/v1` prefix every product
 * route lives under.
 *
 * Same-origin by design. `BACKEND_API_URL` is an internal container address in
 * deployed environments, so the browser cannot fetch the schema directly;
 * routing it through this handler is what makes the Docs Hub work anywhere the
 * app works, and keeps session forwarding consistent with every other proxy.
 */
export async function GET(request: NextRequest) {
  const response = await fetch(backendRootUrl("/openapi.json"), {
    headers: await forwardedHeaders(request),
    cache: "no-store",
  });

  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
