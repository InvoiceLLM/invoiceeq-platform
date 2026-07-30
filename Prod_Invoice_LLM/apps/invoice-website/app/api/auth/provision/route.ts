import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Website path : /api/auth/provision
 * Backend path : /auth/provision
 *
 * Gap 7: the signup page used to call the backend directly from the browser.
 * That cannot work in Azure -- invoice-be.bicep sets `ingress.external: false`,
 * so the backend has no public ingress and the browser can never reach it. The
 * failure was swallowed by a catch, so signup appeared to succeed while no
 * tenant row was ever created.
 *
 * This handler runs on the server, where the internal backend address IS
 * reachable. It also keeps the backend origin out of the client bundle.
 *
 * Note: /auth/provision is mounted on the backend WITHOUT the /api/v1 prefix
 * that every other router uses, so the path is built explicitly here rather
 * than through lib helpers that always append /api/v1.
 *
 * Not authenticated: this runs immediately after signup, before a session token
 * exists to forward, and the backend route takes no auth dependency. Adding
 * verification here overlaps Gap 4 and is deliberately out of scope.
 */
export async function POST(request: NextRequest) {
  // Falls back to the standard local backend port so a fresh clone runs with no
  // env setup. Deployed environments get this from invoice-website.bicep as the
  // backend's internal http:// address.
  const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";

  const body = await request.text();

  try {
    const response = await fetch(
      `${backendApiUrl.replace(/\/$/, "")}/auth/provision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        cache: "no-store",
      }
    );

    const data = await response.text();
    return new NextResponse(data || "{}", {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    // Provisioning is best-effort on the caller's side -- the Clerk user already
    // exists at this point, and the tenant row is created on first authenticated
    // request. Returning 502 rather than throwing keeps the signup flow intact.
    return NextResponse.json(
      { detail: "Backend provision unreachable", error: String(err) },
      { status: 502 }
    );
  }
}
