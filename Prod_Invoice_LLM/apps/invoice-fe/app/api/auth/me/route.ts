import { NextRequest, NextResponse } from "next/server";
import { clerkSessionToken } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/auth/me
 * BE path : /auth/me (unprefixed -- routers/auth.py declares prefix="/auth"
 * and main.py mounts it with `app.include_router(auth.router)`, i.e. with no
 * /api/v1. backendProxy.ts's proxyJson() unconditionally appends /api/v1, so
 * it cannot be used here. Same reason app/api/auth/logout/route.ts hand-rolls
 * its fetch; this follows that pattern.)
 *
 * This is the single source of identity for the FE (hooks/useAuth.ts). It
 * returns the backend's TenantContext: tenant_id, user_id, role, billing_plan,
 * and Feature 1.1's can_train / can_audit / can_load.
 */
export async function GET(request: NextRequest) {
  const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";

  const headers: Record<string, string> = {};
  const inbound = request.headers.get("authorization");
  if (inbound) {
    headers["Authorization"] = inbound;
  } else {
    const token = await clerkSessionToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${backendApiUrl.replace(/\/$/, "")}/auth/me`, {
    headers,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
