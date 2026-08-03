import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/admin/users
 * BE path : /api/v1/admin/users (routers/admin.py) -- Admin-only, tenant-scoped.
 *
 * Unlike /api/auth/me this one CAN use proxyJson: routers/admin.py is mounted
 * with the standard /api/v1 prefix. Authorization is minted server-side by
 * forwardedHeaders(); the backend's require_admin dependency is the actual
 * authorization boundary, this route is only transport.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return proxyJson(request, "/admin/users");
}
