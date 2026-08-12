import { NextRequest, NextResponse } from "next/server";
import { auth } from "@clerk/nextjs/server";

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
 * Gap 133 -- this route is authenticated now. It used to forward an
 * unauthenticated request, and the backend route took no auth dependency, so an
 * anonymous caller could POST an arbitrary clerk_org_id and rename/claim an
 * existing tenant (reproduced against the running dev backend). The token is
 * taken from the caller's own `Authorization` header when the signup page
 * supplied one -- it mints it client-side immediately after `setActive`, which
 * is the freshest possible session state -- and otherwise minted here from the
 * session cookie. The cookie can lag a just-completed `setActive` (see Gap 157),
 * which is exactly why the client-minted token is preferred rather than relying
 * on `auth()` alone.
 *
 * The `invoice-app` template is required, not a bare `getToken()`: the bare
 * session token carries none of this app's custom claims (Gap 109 / Gap 174).
 */
export async function POST(request: NextRequest) {
  // Falls back to the standard local backend port so a fresh clone runs with no
  // env setup. Deployed environments get this from invoice-website.bicep as the
  // backend's internal http:// address.
  const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";

  const body = await request.text();

  let token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || null;
  if (!token) {
    try {
      const { userId, getToken } = await auth();
      if (userId) {
        token = await getToken({ template: "invoice-app" });
      }
    } catch (authErr) {
      console.error("[provision] could not read Clerk session server-side:", authErr);
    }
  }

  if (!token) {
    console.error("[provision] no Clerk session token available; refusing to call backend");
    return NextResponse.json(
      {
        detail:
          "Not signed in. Provisioning requires the session created during sign-up.",
      },
      { status: 401 }
    );
  }

  try {
    const response = await fetch(
      `${backendApiUrl.replace(/\/$/, "")}/auth/provision`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body,
        cache: "no-store",
      }
    );

    const data = await response.text();
    if (!response.ok) {
      // Gap 133: the signup page now blocks on this failure instead of
      // redirecting to /login, so the status/body has to be readable somewhere
      // the user cannot see -- the browser only gets the `detail`.
      console.error(
        `[provision] backend returned ${response.status}:`,
        data || "(empty body)"
      );
    }
    return new NextResponse(data || "{}", {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("[provision] backend unreachable:", err);
    return NextResponse.json(
      { detail: "Backend provision unreachable", error: String(err) },
      { status: 502 }
    );
  }
}
