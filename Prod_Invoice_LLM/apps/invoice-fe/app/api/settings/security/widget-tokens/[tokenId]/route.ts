import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

interface RouteParams {
  params: {
    tokenId: string;
  };
}

/**
 * Feature 17 (FE Gap 325) — revoke one widget token.
 * FE path : /api/settings/security/widget-tokens/{tokenId}
 * BE path : /api/v1/settings/security/widget-tokens/{token_id}
 *
 * Admin-only on the backend, and a 404 when the id is not this tenant's. The
 * backend answers **204**, which `proxyJson` handles explicitly (FE Gap 177:
 * `new NextResponse("", { status: 204 })` throws, so the body is passed as null
 * for null-body statuses) — without that this route would 500 *after* the
 * revocation had already committed.
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  return proxyJson(request, `/settings/security/widget-tokens/${params.tokenId}`);
}
