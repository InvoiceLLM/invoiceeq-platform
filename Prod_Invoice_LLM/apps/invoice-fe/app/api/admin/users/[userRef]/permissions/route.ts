import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/admin/users/{userRef}/permissions
 * BE path : /api/v1/admin/users/{userRef}/permissions (routers/admin.py)
 *
 * Feature 1.1 Task 1.1.6. `userRef` is either the backend users.id UUID (edit
 * time, from GET /api/admin/users) or a Clerk user ID (create time, from
 * POST /api/admin/create-user).
 *
 * The Admin check lives in the backend's `require_admin` dependency, which is
 * the same DB-backed role resolution app/api/admin/create-user/route.js
 * verifies against (website Gap 10) -- deliberately not Clerk's
 * client-editable unsafe_metadata.
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: { userRef: string } }
): Promise<NextResponse> {
  return proxyJson(request, `/admin/users/${encodeURIComponent(params.userRef)}/permissions`);
}
