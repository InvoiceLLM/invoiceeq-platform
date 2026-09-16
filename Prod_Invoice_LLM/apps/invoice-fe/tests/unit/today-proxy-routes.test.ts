/**
 * FE Feature 22 Task 22.0 — the Today proxy routes and the preferences proxy.
 *
 * Every Today route must reach `proxyJson` with the backend path it documents,
 * so a status (403 on an action line, 429 on run-now) arrives intact. The
 * preferences route is the one exception: `/auth` is mounted without /api/v1,
 * so it must go to the backend ROOT — asserted here, because routing it through
 * proxyJson would send every preference read to a 404.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/backendProxy", () => ({
  proxyJson: vi.fn(),
  backendRootUrl: (path: string) => `http://backend.test${path}`,
  forwardedHeaders: vi.fn(),
}));

import { forwardedHeaders, proxyJson } from "@/lib/backendProxy";
import * as today from "@/app/api/today/route";
import * as run from "@/app/api/today/run/route";
import * as questionnaire from "@/app/api/today/questionnaire/route";
import * as questionnaireAnswer from "@/app/api/today/questionnaire/answer/route";
import * as routineAnswers from "@/app/api/today/routine-answers/route";
import * as routineAnswer from "@/app/api/today/routine-answers/[key]/route";
import * as open from "@/app/api/today/[itemId]/open/route";
import * as dismiss from "@/app/api/today/[itemId]/dismiss/route";
import * as scenario from "@/app/api/today/[itemId]/scenario/route";
import * as confirm from "@/app/api/today/[itemId]/confirm/route";
import * as accept from "@/app/api/today/[itemId]/accept/route";
import * as reject from "@/app/api/today/[itemId]/reject/route";
import * as edit from "@/app/api/today/[itemId]/edit/route";
import * as preferences from "@/app/api/auth/me/preferences/route";

const proxy = vi.mocked(proxyJson);
const request = {} as NextRequest;
const item = { params: { itemId: "3f1c-uuid" } };

beforeEach(() => {
  proxy.mockReset();
  proxy.mockResolvedValue("proxied" as any);
});

describe("Today proxy routes (22.0)", () => {
  const cases: [string, () => Promise<unknown>, string][] = [
    ["GET /today", () => today.GET(request), "/today"],
    ["POST /today/run", () => run.POST(request), "/today/run"],
    ["GET /today/questionnaire", () => questionnaire.GET(request), "/today/questionnaire"],
    ["POST /today/questionnaire/answer", () => questionnaireAnswer.POST(request), "/today/questionnaire/answer"],
    ["GET /today/routine-answers", () => routineAnswers.GET(request), "/today/routine-answers"],
    [
      "PATCH /today/routine-answers/{key}",
      () => routineAnswer.PATCH(request, { params: { key: "payment_run" } }),
      "/today/routine-answers/payment_run",
    ],
    ["POST /today/{id}/open", () => open.POST(request, item), "/today/3f1c-uuid/open"],
    ["POST /today/{id}/dismiss", () => dismiss.POST(request, item), "/today/3f1c-uuid/dismiss"],
    ["POST /today/{id}/scenario", () => scenario.POST(request, item), "/today/3f1c-uuid/scenario"],
    ["POST /today/{id}/confirm", () => confirm.POST(request, item), "/today/3f1c-uuid/confirm"],
    ["POST /today/{id}/accept", () => accept.POST(request, item), "/today/3f1c-uuid/accept"],
    ["POST /today/{id}/reject", () => reject.POST(request, item), "/today/3f1c-uuid/reject"],
    ["POST /today/{id}/edit", () => edit.POST(request, item), "/today/3f1c-uuid/edit"],
  ];

  it.each(cases)("%s reaches proxyJson with its backend path", async (_name, call, path) => {
    await expect(call()).resolves.toBe("proxied");
    expect(proxy).toHaveBeenCalledTimes(1);
    expect(proxy).toHaveBeenCalledWith(request, path);
  });

  it("encodes a dynamic segment rather than letting it add a path level", async () => {
    await accept.POST(request, { params: { itemId: "../run" } });
    expect(proxy).toHaveBeenCalledWith(request, "/today/..%2Frun/accept");
  });

  it("every route module opts out of static caching", () => {
    for (const mod of [today, run, questionnaire, questionnaireAnswer, routineAnswers, routineAnswer, open, dismiss, scenario, confirm, accept, reject, edit, preferences]) {
      expect(mod.dynamic).toBe("force-dynamic");
    }
  });
});

describe("preferences proxy (22.0 -> 22.14, 22.21)", () => {
  beforeEach(() => {
    vi.mocked(forwardedHeaders).mockResolvedValue({
      "Content-Type": "application/json",
      Authorization: "Bearer test_admin",
    });
  });

  it("PATCH goes to the unprefixed backend path with body, auth, and the backend's status", async () => {
    const stored = { layout: "classic", first_run_seen: true, tour_seen: false, questionnaire_progress: null };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(stored), { status: 200, headers: { "content-type": "application/json" } }));

    const response = await preferences.PATCH(
      new NextRequest("http://fe.test/api/auth/me/preferences", {
        method: "PATCH",
        body: JSON.stringify({ layout: "classic" }),
      })
    );

    expect(proxy).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://backend.test/auth/me/preferences");
    expect(init).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ layout: "classic" }),
      headers: { Authorization: "Bearer test_admin" },
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(stored);
  });

  it("GET sends no body and forwards a 400 verbatim", async () => {
    const detail = { detail: "Unknown preference keys: ['theme']" };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(detail), { status: 400 }));

    const response = await preferences.GET(new NextRequest("http://fe.test/api/auth/me/preferences"));

    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", body: undefined });
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual(detail);
  });
});
