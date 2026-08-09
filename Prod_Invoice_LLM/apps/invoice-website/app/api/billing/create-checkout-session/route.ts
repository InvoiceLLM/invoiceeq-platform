import { NextRequest, NextResponse } from "next/server";
import { auth } from "@clerk/nextjs/server";

/**
 * FE path : /api/billing/create-checkout-session
 * BE path : /api/v1/billing/create-checkout-session
 *
 * Server-side proxy so the browser never needs the backend's internal URL
 * or a raw Clerk session token in JS -- same shape as the existing
 * /api/auth/provision proxy (Gap 7). Forwards the caller's real Clerk
 * session token so the backend's Admin-role gate
 * (routers/billing.py::create_checkout_session) can actually verify it.
 *
 * Gap 174: under Multi-Zone, invoice-fe's Subscriptions page posts to this
 * website-owned route (billing is not in feApiPrefixes; this app has the
 * local handler). Two bugs here meant PayU never opened even after Gaps
 * 101/120/132 routed the user to a working upgrade CTA:
 *   1. `auth()` was not awaited (Clerk v5 App Router) -- session looked empty
 *      and the handler returned 401.
 *   2. `getToken()` had no template -- Clerk's bare session token omits
 *      org_id/org_role, so the backend resolved Viewer and 403'd Admin-only
 *      checkout (same class as the Gap 109 / backendProxy fix on invoice-fe).
 */
export async function POST(request: NextRequest) {
  const { userId, getToken } = await auth();
  if (!userId) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  const backendApiUrl = process.env.BACKEND_API_URL;
  if (!backendApiUrl) {
    throw new Error("BACKEND_API_URL is not set");
  }

  const token = await getToken({ template: "invoice-app" });
  if (!token) {
    return NextResponse.json(
      { error: "Could not mint a session token for checkout." },
      { status: 401 }
    );
  }

  const body = await request.text();

  const response = await fetch(
    `${backendApiUrl.replace(/\/$/, "")}/api/v1/billing/create-checkout-session`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body,
    }
  );

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
