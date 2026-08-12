import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/admin/dropped-emails
 * BE path : /api/v1/admin/dropped-emails (routers/admin.py) -- Admin-only.
 *
 * BE Gap 124 item 6: inbound mail that was rejected or skipped instead of
 * becoming an invoice. Transport only, exactly like /api/admin/users -- the
 * backend's `require_admin` plus its own tenant-scoping is the authorization
 * boundary, and `proxyJson` forwards the `?limit=` query string through.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return proxyJson(request, "/admin/dropped-emails");
}
