import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/auth/logout
 * BE path : /auth/logout (unprefixed -- auth.router is mounted without
 * /api/v1, unlike every other router, so this can't reuse backendProxy.ts's
 * proxyJson helper, which always appends /api/v1).
 */
export async function POST(request: NextRequest) {
  const backendApiUrl = process.env.BACKEND_API_URL;
  if (!backendApiUrl) {
    throw new Error("BACKEND_API_URL is not set");
  }

  const body = await request.text();
  const response = await fetch(`${backendApiUrl.replace(/\/$/, "")}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
