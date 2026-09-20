// @vitest-environment node
// =============================================================================
// FILE: tests/unit/atlas-briefing-proxy.test.ts
// FEATURE: FE Feature 24 task 24.2 (spec §6, row 24.2) — the SSE proxy.
//
// **NODE, NOT JSDOM.** A Route Handler returns a `NextResponse`, which is a
// `Response` with a real stream body; jsdom's fetch primitives are not the ones
// Next builds on, so this half of §6 runs in the node environment and the
// component half stays in `atlas-briefing.test.tsx`.
//
// THE ASSERTION THAT MATTERS is the last one: a backend 4xx must arrive as an
// `error` frame the panel can render, not as a failed connection. An
// `EventSource` cannot read a status code — a non-2xx with a JSON body is a
// blank panel, which is the failure this handler exists to prevent.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";

// Merges `extra` exactly as the real helper does, so the handler's own
// `Accept: text/event-stream` is proved to reach the backend.
const forwardedHeaders = vi.fn(async (_request: any, extra: Record<string, string> = {}) => ({
  Authorization: "Bearer test_token",
  ...extra,
}));

vi.mock("@/lib/backendProxy", () => ({
  backendUrl: (path: string, search = "") => `http://backend.test/api/v1${path}${search}`,
  forwardedHeaders: (...args: any[]) => (forwardedHeaders as any)(...args),
}));

import { GET } from "@/app/api/atlas/briefing/route";

function request(search = ""): any {
  return {
    method: "GET",
    nextUrl: { search },
    headers: new Headers(),
  };
}

beforeEach(() => {
  forwardedHeaders.mockClear();
});

describe("24.2 GET /api/atlas/briefing", () => {
  it("forwards the auth headers and streams the upstream body through", async () => {
    const body = "event: paragraph\ndata: {\"text\":\"a\",\"citations\":[]}\n\n";
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(request("?x=1"));

    expect(fetchMock).toHaveBeenCalledWith(
      "http://backend.test/api/v1/atlas/briefing?x=1",
      expect.objectContaining({ method: "GET" })
    );
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      Authorization: "Bearer test_token",
      Accept: "text/event-stream",
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toBe(body);

    vi.unstubAllGlobals();
  });

  it("turns a backend 4xx into an error frame, not a blank panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "no grants" }), { status: 403 })
      )
    );

    const response = await GET(request());
    const text = await response.text();

    expect(response.status).toBe(403);
    expect(text).toContain("event: error");
    expect(text).toContain("no grants");
    // Always followed by `done`, so the panel stops waiting.
    expect(text).toContain("event: done");

    vi.unstubAllGlobals();
  });

  it("turns an unreachable backend into an error frame too", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

    const response = await GET(request());
    const text = await response.text();

    expect(response.status).toBe(200);
    expect(text).toContain("event: error");
    expect(text).toContain("ECONNREFUSED");

    vi.unstubAllGlobals();
  });
});
