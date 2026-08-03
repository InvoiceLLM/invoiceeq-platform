import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/connectors/callback/[provider] → BE GET /connectors/callback/{provider}
 *
 * Google/Salesforce land the browser on this route as a full-page navigation
 * (not a fetch call), and the backend responds with a redirect back into the
 * app rather than JSON -- so this can't use proxyJson, which follows
 * redirects server-side and would relay the final page's HTML with a 200
 * status instead of forwarding the redirect itself. `redirect: "manual"`
 * keeps the backend's Location header intact so it can be relayed as a real
 * browser redirect.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  const response = await fetch(
    backendUrl(`/connectors/callback/${params.provider}`, request.nextUrl.search),
    {
      method: "GET",
      headers: await forwardedHeaders(request),
      redirect: "manual",
      cache: "no-store",
    }
  );

  const location = response.headers.get("location");
  if (location && (response.status === 301 || response.status === 302 || response.status === 307 || response.status === 308)) {
    return NextResponse.redirect(location);
  }

  const data = await response.text();
  return new NextResponse(data, { status: response.status });
}
