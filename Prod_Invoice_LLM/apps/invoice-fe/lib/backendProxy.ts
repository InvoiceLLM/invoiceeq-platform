import { NextRequest, NextResponse } from "next/server";
import { auth } from "@clerk/nextjs/server";

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

/**
 * Builds the outbound headers for a backend call.
 *
 * Clerk-list Gap 4 (B1): invoice-fe previously sent no Authorization header to
 * the backend from anywhere, which meant `ALLOW_MOCK_AUTH` could never be
 * turned off in a deployed environment. The token is minted here, server-side,
 * rather than in a client-side axios interceptor, because:
 *   - 37 of 39 route handlers under app/api/** already funnel through this
 *     module, so one change covers all of them -- including the 11 components
 *     that call `fetch("/api/...")` directly and never touch lib/apiClient.ts;
 *   - browser -> route handler is same-origin and already carries the Clerk
 *     session cookie, so the browser never needs to hold a bearer token;
 *   - route handler -> backend is server-to-server, which is where a bearer
 *     token belongs.
 *
 * Precedence, deliberately: an inbound Authorization header always wins. That
 * keeps `Bearer test_*` tooling and the e2e/dev flows working unchanged. Only
 * when there is no inbound header do we mint one from the Clerk session.
 *
 * If there is no Clerk session either, we send nothing rather than fabricating
 * a token -- the backend then decides (401 with enforcement on, mock context
 * with ALLOW_MOCK_AUTH on). Flipping that flag is a deployment decision, not
 * this function's job.
 */
export async function forwardedHeaders(
  request: NextRequest,
  extra: Record<string, string> = {}
): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...extra };

  const inbound = request.headers.get("authorization");
  if (inbound) {
    headers["Authorization"] = inbound;
    return headers;
  }

  const token = await clerkSessionToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/**
 * Mints a Clerk session token for the current request, or null if there is no
 * signed-in session.
 *
 * Wrapped in try/catch because `auth()` throws when clerkMiddleware() has not
 * run for the current path (middleware.ts's matcher covers /api/*, but a
 * proxy helper shouldn't hard-fail on a config change) and `getToken()` can
 * reject transiently. Either way the correct behaviour is "no token", not a
 * 500 on every proxied call.
 */
export async function clerkSessionToken(): Promise<string | null> {
  try {
    const { userId, getToken } = await auth();
    if (!userId) return null;
    return (await getToken()) ?? null;
  } catch {
    return null;
  }
}

/** Proxies a plain JSON request/response to the backend, forwarding method, query string, body, and auth header. */
export async function proxyJson(request: NextRequest, path: string): Promise<NextResponse> {
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(backendUrl(path, request.nextUrl.search), {
    method: request.method,
    headers: await forwardedHeaders(request, { "Content-Type": "application/json" }),
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
