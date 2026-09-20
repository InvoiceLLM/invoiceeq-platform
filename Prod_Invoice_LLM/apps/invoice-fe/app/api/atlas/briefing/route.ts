// =============================================================================
// FILE: app/api/atlas/briefing/route.ts
// FEATURE: FE Feature 24 task 24.2 (spec §2) — the SSE proxy for BE Feature 35's
//          `GET /api/v1/atlas/briefing`.
//
// Same shape as `app/api/chat/jobs/[jobId]/stream/route.ts`, deliberately: that
// handler is the one place in this app that already streams a backend response
// through, and the four headers below are what make a stream arrive as a stream
// rather than in one lump when a reverse proxy sits in front of the container.
//
// `proxyJson` is NOT used here and must not be: it reads the whole body with
// `response.text()` before replying, which would buffer the entire briefing and
// defeat the reason the backend wrote it as a generator at all.
//
// AN UPSTREAM FAILURE IS NOT A BLANK PANEL (spec §6, task 24.2). A non-2xx is
// turned into a real `error` frame followed by `done`, so the panel says what
// happened in its own body instead of showing an empty briefing — and so does a
// connection that never got made. The browser's `EventSource` cannot read a
// status code, only frames.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";

import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache, no-transform",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

/** One SSE frame in BE 35 §3.3's shape. */
function frame(type: string, data: unknown): string {
  // hardcode-ok: the SSE wire format itself (BE 35 §3.3), not content. No
  // figure passes through here — `data` is JSON-encoded whole.
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** An `error` + `done` pair, as the stream the panel is already reading. */
function errorStream(message: string, status = 200): NextResponse {
  const body =
    frame("error", { message }) +
    frame("done", { cached: false, model: "", dropped_paragraphs: 0 });
  return new NextResponse(body, { status, headers: SSE_HEADERS });
}

/** GET /api/atlas/briefing → BE GET /api/v1/atlas/briefing, streamed. */
export async function GET(request: NextRequest) {
  const url = backendUrl("/atlas/briefing", request.nextUrl.search);
  const headers = await forwardedHeaders(request, { Accept: "text/event-stream" });

  try {
    const upstream = await fetch(url, { method: "GET", headers, cache: "no-store" });

    if (!upstream.ok) {
      // The status is kept (the browser still sees a 4xx/5xx on the network
      // tab) and the body is replaced by frames, because an EventSource only
      // ever surfaces "the connection failed" for a non-2xx and the user would
      // get a silent empty panel.
      const detail = await upstream.text().catch(() => "");
      return errorStream(
        detail
          ? `ATLAS could not write your briefing (${upstream.status}): ${detail}` // hardcode-ok: an HTTP status in a failure sentence, not a figure
          : `ATLAS could not write your briefing (${upstream.status}).`, // hardcode-ok: an HTTP status in a failure sentence, not a figure
        upstream.status
      );
    }

    return new NextResponse(upstream.body, { status: 200, headers: SSE_HEADERS });
  } catch (err: any) {
    return errorStream(
      `ATLAS could not be reached: ${err?.message ?? "connection failed"}` // hardcode-ok: the transport error text, not a figure
    );
  }
}
