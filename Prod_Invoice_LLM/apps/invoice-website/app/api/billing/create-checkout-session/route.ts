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
 */
export async function POST(request: NextRequest) {
  const { userId, getToken } = auth();
  if (!userId) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  const backendApiUrl = process.env.BACKEND_API_URL;
  if (!backendApiUrl) {
    throw new Error("BACKEND_API_URL is not set");
  }

  const token = await getToken();
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
