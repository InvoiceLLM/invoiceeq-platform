// =============================================================================
// FILE: app/api/chat/jobs/[jobId]/stream/route.ts
// FEATURE: Gap 280 — Queue-based Chat Architecture & SSE Stream Proxy
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function GET(
  request: NextRequest,
  { params }: { params: { jobId: string } }
) {
  const backendStreamUrl = backendUrl(`/chat/jobs/${params.jobId}/stream`, request.nextUrl.search);
  const headers = await forwardedHeaders(request);

  try {
    const upstreamRes = await fetch(backendStreamUrl, {
      method: "GET",
      headers,
    });

    if (!upstreamRes.ok) {
      return new NextResponse(upstreamRes.body, {
        status: upstreamRes.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new NextResponse(upstreamRes.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: "Failed to connect to chat SSE stream", details: err?.message },
      { status: 502 }
    );
  }
}
