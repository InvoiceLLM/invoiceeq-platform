import { NextRequest, NextResponse } from "next/server";

// Gap 2: falls back to the standard local backend port so a fresh clone runs
// without env setup, matching app/api/auth/logout/route.ts which already does
// this. Previously this threw, turning a missing env var into an opaque 500 on
// every proxied API call. Deployed environments set BACKEND_API_URL explicitly
// via infra/modules/compute/invoice-fe.bicep.
const DEFAULT_LOCAL_BACKEND_URL = "http://localhost:8000";

function backendBaseUrl(): string {
  const url = process.env.BACKEND_API_URL || DEFAULT_LOCAL_BACKEND_URL;
  return `${url.replace(/\/$/, "")}/api/v1`;
}

/** Builds the full backend URL for a given API path, preserving the incoming query string. */
export function backendUrl(path: string, search = ""): string {
  return `${backendBaseUrl()}${path}${search}`;
}

/** Forwards the Authorization header from the incoming request, if present. */
export function forwardedHeaders(
  request: NextRequest,
  extra: Record<string, string> = {}
): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const authHeader = request.headers.get("authorization");
  if (authHeader) headers["Authorization"] = authHeader;
  return headers;
}

/** Proxies a plain JSON request/response to the backend, forwarding method, query string, body, and auth header. */
export async function proxyJson(request: NextRequest, path: string): Promise<NextResponse> {
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(backendUrl(path, request.nextUrl.search), {
    method: request.method,
    headers: forwardedHeaders(request, { "Content-Type": "application/json" }),
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  const data = await response.text();
  const headers: Record<string, string> = {
    "Content-Type": response.headers.get("content-type") || "application/json",
  };
  // FE Gap 29: GET /invoices reports its full matching count here so callers
  // can page through the tenant's full result set instead of client-slicing
  // one fetched batch -- forward it through untouched when present.
  const totalCount = response.headers.get("x-total-count");
  if (totalCount) headers["X-Total-Count"] = totalCount;

  return new NextResponse(data, { status: response.status, headers });
}
