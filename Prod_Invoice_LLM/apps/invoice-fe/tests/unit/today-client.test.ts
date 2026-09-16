/**
 * FE Feature 22 Task 22.0 — `lib/today.ts`, the Today surface's client.
 *
 * What is asserted is the contract every later Today task leans on:
 *   - the client hands back exactly what the server sent, in the server's
 *     order (a mutated, deliberately un-sorted fixture — a client-side sort or
 *     filter fails the test rather than passing it);
 *   - a 429 from run-now is a result carrying the server's seconds, not an
 *     exception, while every other failure still throws;
 *   - the pre-onboarding branch cannot be skipped at compile time.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";

vi.mock("@/lib/apiClient", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";
import {
  type TodayActive,
  type TodayInputRequest,
  type TodayResponse,
  editConvention,
  formatUnlockValue,
  getQuestionnaire,
  getInboxAddress,
  getToday,
  isPreOnboarding,
  runNow,
  runScenario,
  todayErrorOf,
  updatePreferences,
  updateRoutineAnswer,
  uploadDocuments,
} from "@/lib/today";

const get = vi.mocked(apiClient.get);
const post = vi.mocked(apiClient.post);
const patch = vi.mocked(apiClient.patch);

function httpError(status: number, data: unknown): AxiosError {
  return new AxiosError(`Request failed with status code ${status}`, "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    statusText: "",
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  });
}

function activeFixture(): TodayActive {
  return {
    state: "active",
    docs_seen: 42,
    docs_required: 10,
    // Two currencies, never blended into one line.
    position_lines: [
      { currency: "USD", text: "USD cash covers 40 days.", position: 18250.5 },
      { currency: "INR", text: "INR cash covers 12 days.", position: 912000 },
    ],
    // Deliberately NOT in severity order: the server's order is the order.
    findings: [
      {
        id: "f-3",
        section: "findings",
        text: "Rajesh Steel over-billed PO-1041.",
        seeded_question: "Why did Rajesh over-bill PO-1041?",
        severity: 3,
        meta: null,
        clearance: "ops",
        created_at: "2026-09-16T06:00:00",
      },
      {
        id: "f-1",
        section: "findings",
        text: "Salary run exceeds the approval threshold.",
        seeded_question: null,
        severity: 1,
        meta: { action: "hold_payment" },
        clearance: "exec",
        created_at: null,
      },
    ],
    summary: [{ id: "s-1", section: "summary", text: "Five invoices due this week.", severity: 2, created_at: null }],
    input_requests: [],
    proposals: [],
    next_question: null,
  };
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
});

describe("getToday (22.0)", () => {
  it("returns the server's payload untouched — no sort, filter or blend", async () => {
    const fixture = activeFixture();
    const expected = structuredClone(fixture);
    get.mockResolvedValueOnce({ data: fixture });

    const result = await getToday();

    expect(get).toHaveBeenCalledWith("/today");
    expect(result).toEqual(expected);
    if (isPreOnboarding(result)) throw new Error("fixture is active");
    expect(result.findings.map((f) => f.id)).toEqual(["f-3", "f-1"]);
    expect(result.position_lines.map((p) => p.currency)).toEqual(["USD", "INR"]);
  });

  it("narrows pre-onboarding, which carries no analysis at all", async () => {
    get.mockResolvedValueOnce({ data: { state: "pre_onboarding", docs_seen: 4, docs_required: 10 } });

    const result = await getToday();

    expect(isPreOnboarding(result)).toBe(true);
    expect(Object.keys(result).sort()).toEqual(["docs_required", "docs_seen", "state"]);
  });

  it("makes the pre-onboarding branch impossible to skip at compile time", () => {
    const response = activeFixture() as TodayResponse;
    // @ts-expect-error — `findings` does not exist until `state` is narrowed (task 22.25).
    expect(response.findings).toBeDefined();
    if (!isPreOnboarding(response)) expect(response.findings).toHaveLength(2);
  });
});

describe("runNow (22.0 -> 22.23)", () => {
  it("returns the enqueued job", async () => {
    post.mockResolvedValueOnce({ data: { ok: true, job_id: "job-7", status: "enqueued", cooldown_seconds: 900 } });

    const result = await runNow();

    expect(post).toHaveBeenCalledWith("/today/run");
    expect(result).toMatchObject({ kind: "enqueued", job_id: "job-7", cooldown_seconds: 900 });
  });

  it("turns a 429 into a result carrying the server's retry_after_seconds", async () => {
    post.mockRejectedValueOnce(
      httpError(429, { detail: "Rate limit exceeded. ATLAS run is cooling down.", retry_after_seconds: 437 })
    );

    const result = await runNow();

    expect(result).toEqual({
      kind: "cooling_down",
      retry_after_seconds: 437,
      detail: "Rate limit exceeded. ATLAS run is cooling down.",
    });
  });

  it("still throws a 403 — only the cooldown is an expected outcome", async () => {
    post.mockRejectedValueOnce(httpError(403, { detail: "Only Admins can trigger an immediate ATLAS run" }));

    await expect(runNow()).rejects.toBeInstanceOf(AxiosError);
  });
});

describe("todayErrorOf (22.0 -> 22.19)", () => {
  it("surfaces the backend's own words for a line to render", () => {
    expect(todayErrorOf(httpError(403, { detail: "Auditor cannot confirm hold_payment" }))).toEqual({
      status: 403,
      detail: "Auditor cannot confirm hold_payment",
    });
  });

  it("returns null for a non-HTTP failure", () => {
    expect(todayErrorOf(new Error("boom"))).toBeNull();
  });
});

describe("formatUnlockValue (22.0 -> 22.5)", () => {
  const base: TodayInputRequest = {
    id: "r-1",
    kind: "contract",
    phrase: "Attach your Rajesh contract",
    unlock_amount: null,
    unlock_currency: null,
    unlock_count: null,
  };

  it("formats both of the backend's figures without computing a new one", () => {
    expect(formatUnlockValue({ ...base, unlock_amount: 220000, unlock_currency: "INR", unlock_count: 5 })).toBe(
      `${formatCurrency(220000, "INR")} across 5 invoices`
    );
  });

  it("singularises one invoice", () => {
    expect(formatUnlockValue({ ...base, unlock_count: 1 })).toBe("1 invoice");
  });

  it("draws nothing when the request states no unlock value", () => {
    expect(formatUnlockValue(base)).toBeNull();
  });
});

describe("getInboxAddress / uploadDocuments (22.25)", () => {
  it("returns the backend's mailbox", async () => {
    get.mockResolvedValueOnce({ data: { mailbox: "invoices@acme.invoiceeq.app" } });
    await expect(getInboxAddress()).resolves.toBe("invoices@acme.invoiceeq.app");
    expect(get).toHaveBeenCalledWith("/email/settings/mailbox");
  });

  it("returns null — never a guessed address — when the mailbox is empty or unreadable", async () => {
    get.mockResolvedValueOnce({ data: { mailbox: "  " } });
    await expect(getInboxAddress()).resolves.toBeNull();
    get.mockRejectedValueOnce(httpError(500, {}));
    await expect(getInboxAddress()).resolves.toBeNull();
  });

  it("uploads every file under the Ingest endpoint's `files` field", async () => {
    post.mockResolvedValueOnce({ data: { batch_id: "b1", job_ids: ["j1", "j2"] } });
    const files = [new File(["a"], "a.pdf"), new File(["b"], "b.pdf")];
    await expect(uploadDocuments(files)).resolves.toEqual({ batch_id: "b1", job_ids: ["j1", "j2"] });
    const [url, body] = post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/invoices/upload");
    expect((body.getAll("files") as File[]).map((file) => file.name)).toEqual(["a.pdf", "b.pdf"]);
  });
});

describe("request shapes match the backend's request models", () => {
  it("scenario defaults horizon_days to the backend's 90", async () => {
    post.mockResolvedValueOnce({ data: { ok: true } });
    await runScenario("item-1", { change: { delay_days: 14 } });
    expect(post).toHaveBeenCalledWith("/today/item-1/scenario", { change: { delay_days: 14 }, horizon_days: 90 });
  });

  it("edit sends rule_text + target (EditConventionRequest)", async () => {
    post.mockResolvedValueOnce({ data: { ok: true, rule_id: "r", rule_text: "Freight is not taxable" } });
    await editConvention("freight_tax", "Freight is not taxable");
    expect(post).toHaveBeenCalledWith("/today/freight_tax/edit", {
      rule_text: "Freight is not taxable",
      target: "tenant_chat_rule",
    });
  });

  it("questionnaire forwards the path as a query parameter", async () => {
    get.mockResolvedValueOnce({ data: { completed: true, question: null } });
    await getQuestionnaire("ingest");
    expect(get).toHaveBeenCalledWith("/today/questionnaire", { params: { path: "ingest" } });
  });

  it("encodes path segments", async () => {
    patch.mockResolvedValueOnce({ data: { ok: true } });
    await updateRoutineAnswer("a/b c", "month_end");
    expect(patch).toHaveBeenCalledWith("/today/routine-answers/a%2Fb%20c", { value: "month_end" });
  });

  it("preferences go to /auth/me/preferences, never localStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    patch.mockResolvedValueOnce({
      data: { layout: "classic", first_run_seen: false, tour_seen: false, questionnaire_progress: null },
    });

    const prefs = await updatePreferences({ layout: "classic" });

    expect(patch).toHaveBeenCalledWith("/auth/me/preferences", { layout: "classic" });
    expect(prefs.layout).toBe("classic");
    expect(setItem).not.toHaveBeenCalled();
  });
});
