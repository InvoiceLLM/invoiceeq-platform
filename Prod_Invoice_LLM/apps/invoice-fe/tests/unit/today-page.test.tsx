/**
 * FE Feature 22 Task 22.4 — Today core.
 *
 * Section rule: founder ruling 2026-09-16 (Option B) — one section per backend
 * list, server order kept, empty lists absent. Fixtures are deliberately NOT in
 * severity order and carry two currencies, so a client-side sort, filter or
 * blended total fails a test rather than passing one.
 *
 * Live refresh: no `today_updated` event exists in the backend yet, so Today
 * polls (TODAY_POLL_MS) and refetches when the tab becomes visible.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { AxiosError, AxiosHeaders } from "axios";

const auth = vi.hoisted(() => ({ current: { loading: false, role: "Admin", canLoad: true } }));
const nav = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, replace: vi.fn() }) }));

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("@/lib/today", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/today")>();
  return {
    ...actual,
    getToday: vi.fn(),
    getInboxAddress: vi.fn(),
    uploadDocuments: vi.fn(),
    openTodayItem: vi.fn(),
    getRoutineAnswers: vi.fn(async () => ({ answers: {}, contradictions: [] })),
  };
});
// The Ingest screen's DropZone is reused as-is; here it is a stand-in that
// "selects" one file, so the test drives the upload flow, not file validation.
vi.mock("@/components/ingestion/DropZone", () => ({
  default: ({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) => (
    <button type="button" onClick={() => onChange([new File(["%PDF"], "raj-2008.pdf", { type: "application/pdf" })])}>
      pick a file ({files.length} selected)
    </button>
  ),
}));

import TodayPage from "@/app/today/page";
import { TODAY_POLL_MS } from "@/hooks/useToday";
import {
  formatUnlockValue,
  getInboxAddress,
  getToday,
  openTodayItem,
  todaySections,
  uploadDocuments,
  type TodayActive,
} from "@/lib/today";

const getTodayMock = vi.mocked(getToday);
const inboxMock = vi.mocked(getInboxAddress);
const uploadMock = vi.mocked(uploadDocuments);
const openMock = vi.mocked(openTodayItem);

function adminToday(): TodayActive {
  return {
    state: "active",
    docs_seen: 42,
    docs_required: 10,
    position_lines: [
      { currency: "USD", text: "USD cash covers 40 days.", position: 18250.5 },
      { currency: "INR", text: "INR cash covers 12 days.", position: 912000 },
    ],
    findings: [
      { id: "f3", section: "findings", text: "Rajesh Steel over-billed PO-1041.", seeded_question: null, severity: 3, meta: null, clearance: "ops", created_at: null },
      { id: "f1", section: "findings", text: "Salary run exceeds the approval threshold.", seeded_question: null, severity: 1, meta: null, clearance: "exec", created_at: null },
    ],
    summary: [],
    input_requests: [
      { id: "r1", kind: "contract", phrase: "Attach your Rajesh contract", unlock_amount: 220000, unlock_currency: "INR", unlock_count: 5 },
    ],
    proposals: [],
    next_question: null,
  };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  getTodayMock.mockReset();
  inboxMock.mockReset();
  uploadMock.mockReset();
  openMock.mockReset();
  nav.push.mockReset();
  inboxMock.mockResolvedValue("invoices@acme.invoiceeq.app");
  auth.current = { loading: false, role: "Admin", canLoad: true };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("todaySections (Option B)", () => {
  it("maps each list to its section, in the ruled order, keeping server order and omitting empty lists", () => {
    const sections = todaySections({
      ...adminToday(),
      proposals: [{ id: "p1", kind: "freight", title: "Stop flagging freight lines", description: "Seen on 6 invoices", suggested_rule: "", evidence: {} }],
      summary: [{ id: "s1", section: "summary", text: "Five invoices due this week.", severity: 2, created_at: null }],
    });
    expect(sections.map((s) => [s.title, s.lines.map((l) => l.text)])).toEqual([
      ["Cash", ["USD cash covers 40 days.", "INR cash covers 12 days."]],
      ["Needs you", ["Attach your Rajesh contract"]],
      ["Decide", ["Stop flagging freight lines"]],
      ["Findings", ["Rajesh Steel over-billed PO-1041.", "Salary run exceeds the approval threshold."]],
      ["This week", ["Five invoices due this week."]],
    ]);
  });

  it("carries the server's second line without computing one", () => {
    const [, needsYou] = todaySections(adminToday());
    expect(needsYou.lines[0].detail).toBe(formatUnlockValue(adminToday().input_requests[0]));
  });
});

describe("TodayPage (22.4)", () => {
  it("renders 5 lines across 3 sections in server order", async () => {
    getTodayMock.mockResolvedValue(adminToday());
    render(<TodayPage />);
    await screen.findByText("Salary run exceeds the approval threshold.");

    const sections = screen.getAllByRole("region");
    expect(sections.map((s) => within(s).getByRole("heading").textContent)).toEqual(["Cash", "Needs you", "Findings"]);
    expect(screen.getAllByRole("listitem").map((li) => li.querySelector("p")?.textContent)).toEqual([
      "USD cash covers 40 days.",
      "INR cash covers 12 days.",
      "Attach your Rajesh contract",
      "Rajesh Steel over-billed PO-1041.",
      "Salary run exceeds the approval threshold.",
    ]);
  });

  it("a clerk's payload (no cash, no proposals) renders no Cash or Decide section — the FE filters nothing", async () => {
    getTodayMock.mockResolvedValue({ ...adminToday(), position_lines: [], proposals: [] });
    render(<TodayPage />);
    await screen.findByText("Attach your Rajesh contract");
    expect(screen.queryByTestId("today-section-cash")).toBeNull();
    expect(screen.queryByTestId("today-section-decide")).toBeNull();
  });

  it("pre-onboarding shows the server's progress and no lines at all", async () => {
    getTodayMock.mockResolvedValue({ state: "pre_onboarding", docs_seen: 4, docs_required: 10 });
    render(<TodayPage />);
    expect(await screen.findByTestId("today-pre-onboarding")).toHaveTextContent("4 of 10 documents");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("an active tenant with nothing to show gets the empty state", async () => {
    getTodayMock.mockResolvedValue({ ...adminToday(), position_lines: [], findings: [], input_requests: [] });
    render(<TodayPage />);
    expect(await screen.findByTestId("today-empty")).toBeInTheDocument();
  });

  it("polls once per interval and refetches when the tab becomes visible", async () => {
    vi.useFakeTimers();
    getTodayMock.mockResolvedValue(adminToday());
    render(<TodayPage />);
    await flush();
    expect(getTodayMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TODAY_POLL_MS);
    });
    expect(getTodayMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(getTodayMock).toHaveBeenCalledTimes(3);
  });

  it("a failed refresh keeps the last list on screen and says so", async () => {
    vi.useFakeTimers();
    getTodayMock.mockResolvedValueOnce(adminToday()).mockRejectedValueOnce(new Error("network down"));
    render(<TodayPage />);
    await flush();
    expect(screen.getByText("Attach your Rajesh contract")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TODAY_POLL_MS);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Showing the last loaded list");
    expect(screen.getByText("Attach your Rajesh contract")).toBeInTheDocument();
  });
});

describe("PreOnboardingToday (22.25)", () => {
  const preOnboarding = { state: "pre_onboarding" as const, docs_seen: 4, docs_required: 10 };

  it("shows the server's progress, the inbox address and the drop zone — and no analysis at all", async () => {
    getTodayMock.mockResolvedValue(preOnboarding);
    render(<TodayPage />);

    expect(await screen.findByTestId("today-pre-onboarding-progress")).toHaveTextContent("4 of 10 documents so far");
    expect(await screen.findByTestId("today-inbox")).toHaveTextContent("invoices@acme.invoiceeq.app");
    expect(screen.getByTestId("today-drop-zone")).toBeInTheDocument();
    expect(screen.queryAllByRole("region")).toHaveLength(0);
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("never invents an inbox address when the backend has none", async () => {
    inboxMock.mockResolvedValue(null);
    getTodayMock.mockResolvedValue(preOnboarding);
    render(<TodayPage />);
    await screen.findByTestId("today-pre-onboarding");
    await waitFor(() => expect(inboxMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("today-inbox")).toBeNull();
    expect(screen.getByTestId("today-pre-onboarding")).not.toHaveTextContent("@");
  });

  it("without the ingest permission there is no drop zone, and the user is told who can upload", async () => {
    auth.current = { loading: false, role: "Auditor", canLoad: false };
    getTodayMock.mockResolvedValue(preOnboarding);
    render(<TodayPage />);
    expect(await screen.findByTestId("today-no-upload-permission")).toBeInTheDocument();
    expect(screen.queryByTestId("today-drop-zone")).toBeNull();
  });

  it("uploads through the Ingest endpoint, confirms, and re-reads Today — which flips to the list once past the threshold", async () => {
    getTodayMock.mockResolvedValueOnce(preOnboarding).mockResolvedValue(adminToday());
    uploadMock.mockResolvedValue({ batch_id: "b1", job_ids: ["j1"] });
    render(<TodayPage />);

    const upload = await screen.findByRole("button", { name: /^Upload/ });
    expect(upload).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /pick a file/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Upload/ }));
    });

    expect(uploadMock).toHaveBeenCalledTimes(1);
    expect(uploadMock.mock.calls[0][0].map((file) => file.name)).toEqual(["raj-2008.pdf"]);
    expect(getTodayMock).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Attach your Rajesh contract")).toBeInTheDocument();
    expect(screen.queryByTestId("today-pre-onboarding")).toBeNull();
  });

  it("a billing refusal (402) is explained, not a generic error", async () => {
    getTodayMock.mockResolvedValue(preOnboarding);
    uploadMock.mockRejectedValue(
      new AxiosError("Payment Required", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 402,
        statusText: "",
        data: {},
        headers: {},
        config: { headers: new AxiosHeaders() },
      })
    );
    render(<TodayPage />);
    fireEvent.click(await screen.findByRole("button", { name: /pick a file/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Upload/ }));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Billing limit reached");
    expect(getTodayMock).toHaveBeenCalledTimes(1);
  });
});


describe("Today lines lead into Ask (22.5)", () => {
  function withSummary(): TodayActive {
    return {
      ...adminToday(),
      summary: [{ id: "s1", section: "summary", text: "Five invoices due this week.", severity: 2, created_at: null }],
    };
  }

  it("a finding opens Ask exactly once, with the returned session and seeded question", async () => {
    getTodayMock.mockResolvedValue(withSummary());
    let resolveOpen: (value: { session_id: string; seeded_question: string; item_id: string }) => void = () => undefined;
    openMock.mockImplementation(() => new Promise((resolve) => (resolveOpen = resolve)));
    render(<TodayPage />);

    const line = await screen.findByRole("button", { name: /Rajesh Steel over-billed PO-1041/ });
    fireEvent.click(line);
    fireEvent.click(line);
    expect(openMock).toHaveBeenCalledTimes(1);
    expect(openMock).toHaveBeenCalledWith("f3");
    expect(line).toBeDisabled();

    await act(async () => {
      resolveOpen({ session_id: "sess-9", seeded_question: "Why did Rajesh over-bill PO-1041?", item_id: "f3" });
    });
    expect(nav.push).toHaveBeenCalledTimes(1);
    expect(nav.push).toHaveBeenCalledWith("/ask?session=sess-9&seed=Why+did+Rajesh+over-bill+PO-1041%3F");
  });

  it("summary lines open Ask too", async () => {
    getTodayMock.mockResolvedValue(withSummary());
    openMock.mockResolvedValue({ session_id: "sess-2", seeded_question: "", item_id: "s1" });
    render(<TodayPage />);
    const line = await screen.findByRole("button", { name: /Five invoices due this week/ });
    await act(async () => {
      fireEvent.click(line);
    });
    expect(openMock).toHaveBeenCalledWith("s1");
    expect(nav.push).toHaveBeenCalledWith("/ask?session=sess-2");
  });

  it("a failed open is shown on the line, and nothing navigates", async () => {
    getTodayMock.mockResolvedValue(adminToday());
    openMock.mockRejectedValue(
      new AxiosError("Not Found", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 404,
        statusText: "",
        data: { detail: "Today item not found" },
        headers: {},
        config: { headers: new AxiosHeaders() },
      })
    );
    render(<TodayPage />);
    const line = await screen.findByRole("button", { name: /Salary run exceeds/ });
    await act(async () => {
      fireEvent.click(line);
    });
    expect(within(line.closest("li")!).getByRole("alert")).toHaveTextContent("Today item not found");
    expect(nav.push).not.toHaveBeenCalled();
    expect(line).toBeEnabled();
  });

  it("an input request goes straight to Ask with attach=1, without calling open", async () => {
    getTodayMock.mockResolvedValue(adminToday());
    render(<TodayPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Attach your Rajesh contract/ }));
    expect(nav.push).toHaveBeenCalledWith("/ask?attach=1");
    expect(openMock).not.toHaveBeenCalled();
  });

  it("two currencies are two cash lines, not clickable, and never a blended total", async () => {
    getTodayMock.mockResolvedValue(adminToday());
    render(<TodayPage />);
    await screen.findByText("USD cash covers 40 days.");
    const cash = screen.getByTestId("today-section-cash");
    expect(within(cash).getAllByTestId("today-line-position").map((li) => li.textContent)).toEqual([
      "USD cash covers 40 days.",
      "INR cash covers 12 days.",
    ]);
    // The lines themselves are not clickable (the section also holds the 22.20 scenario control).
    for (const line of within(cash).getAllByTestId("today-line-position")) {
      expect(within(line).queryAllByRole("button")).toHaveLength(0);
    }
    expect(cash.textContent).not.toMatch(/total/i);
  });
});


describe("Today shows the routine questionnaire to the owner (22.22)", () => {
  const withQuestion = (): TodayActive => ({
    ...adminToday(),
    next_question: {
      key: "payment_run",
      prompt: "When do you normally pay your suppliers?",
      chips: ["weekly_run"],
      free_text: true,
      skippable: true,
      answer_kind: "text",
      default_value: null,
    },
  });

  it("an Admin sees the question above the list", async () => {
    getTodayMock.mockResolvedValue(withQuestion());
    render(<TodayPage />);
    expect(await screen.findByTestId("questionnaire-card")).toHaveTextContent("When do you normally pay your suppliers?");
  });

  it("other roles do not", async () => {
    auth.current = { loading: false, role: "Auditor", canLoad: true };
    getTodayMock.mockResolvedValue(withQuestion());
    render(<TodayPage />);
    await screen.findByText("Attach your Rajesh contract");
    expect(screen.queryByTestId("questionnaire-card")).toBeNull();
  });
});
