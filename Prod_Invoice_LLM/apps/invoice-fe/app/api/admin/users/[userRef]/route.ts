import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : DELETE /api/admin/users/{userRef}
 * BE path : DELETE /api/v1/admin/users/{userRef} (routers/admin.py)
 *
 * FE Gap 168. The Admin console's "Remove" button had nothing behind it -- it
 * filtered the row out of local React state, so a "removed" user kept their
 * sign-in and every permission, and came back on the next page load.
 *
 * Removal is two things, in this order:
 *   1. the backend detaches/deletes their tenant row (Admin-only, tenant-scoped
 *      -- `require_admin` there is the authorization boundary, this route is
 *      not; it deliberately does the backend call FIRST so a non-Admin caller
 *      is rejected before anything touches Clerk);
 *   2. this route deletes their Clerk account, which is what actually revokes
 *      sign-in. Clerk user administration lives here rather than in the backend
 *      because this is the side that holds CLERK_SECRET_KEY -- the same split
 *      `POST /api/admin/create-user` already uses to create the account.
 *
 * Not a `proxyJson()` call for that reason: the Clerk step needs the backend's
 * response body (the user's clerk_user_id), and its own outcome has to be
 * reported honestly. A failed Clerk delete returns 200 with
 * `clerkDeleted: false` plus a warning rather than a bare success -- the tenant
 * data is genuinely gone at that point, but the account can still sign in, and
 * this gap exists precisely because the UI used to imply more than had happened.
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { userRef: string } }
): Promise<NextResponse> {
  const backendRes = await fetch(
    backendUrl(`/admin/users/${encodeURIComponent(params.userRef)}`),
    {
      method: "DELETE",
      headers: await forwardedHeaders(request, { "Content-Type": "application/json" }),
      cache: "no-store",
    }
  );

  const body = await backendRes.text();
  if (!backendRes.ok) {
    return new NextResponse(body, {
      status: backendRes.status,
      headers: {
        "Content-Type": backendRes.headers.get("content-type") || "application/json",
      },
    });
  }

  let removed: { clerk_user_id?: string; detached?: boolean } = {};
  try {
    removed = JSON.parse(body);
  } catch {
    // A 2xx with an unparseable body still means the backend removal happened;
    // there is just no Clerk id to act on below.
  }

  const secretKey = process.env.CLERK_SECRET_KEY;
  const clerkUserId = removed.clerk_user_id;

  if (!secretKey || !clerkUserId) {
    return NextResponse.json({
      success: true,
      detached: removed.detached === true,
      clerkDeleted: false,
      warning:
        "Removed from this workspace, but their sign-in account was not deleted (Clerk is not configured on this server). Delete it in Clerk to fully revoke access.",
    });
  }

  try {
    const clerkRes = await fetch(`https://api.clerk.com/v1/users/${clerkUserId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${secretKey}` },
    });

    // 404 means the Clerk account is already gone -- the end state we wanted.
    if (!clerkRes.ok && clerkRes.status !== 404) {
      const detail = await clerkRes.json().catch(() => ({}));
      const reason =
        detail?.errors?.[0]?.long_message || detail?.errors?.[0]?.message || `HTTP ${clerkRes.status}`;
      console.error("Clerk user delete failed:", reason);
      return NextResponse.json({
        success: true,
        detached: removed.detached === true,
        clerkDeleted: false,
        warning: `Removed from this workspace, but their sign-in account could not be deleted (${reason}). Delete it in Clerk to fully revoke access.`,
      });
    }
  } catch (err: any) {
    console.error("Clerk user delete threw:", err);
    return NextResponse.json({
      success: true,
      detached: removed.detached === true,
      clerkDeleted: false,
      warning:
        "Removed from this workspace, but their sign-in account could not be deleted (Clerk was unreachable). Delete it in Clerk to fully revoke access.",
    });
  }

  return NextResponse.json({
    success: true,
    detached: removed.detached === true,
    clerkDeleted: true,
  });
}
