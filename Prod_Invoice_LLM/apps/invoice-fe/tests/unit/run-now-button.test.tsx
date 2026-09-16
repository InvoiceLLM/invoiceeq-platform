/**
 * FE Feature 22 Task 22.23 — RunNowButton.
 *
 * Admin only. A queued run and a 429 both disable the button and count down on
 * the button itself, from the SERVER's seconds (never a hardcoded 600) — and no
 * toast. Any other failure is shown beside the button.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { AxiosError, AxiosHeaders } from "axios";

const auth = vi.hoisted(() => ({ current: { role: "Admin", loading: false } }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("@/lib/today", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/today")>();
  return { ...actual, runNow: vi.fn() };
});

import RunNowButton, { formatCountdown } from "@/components/today/RunNowButton";
import { runNow } from "@/lib/today";

const runNowMock = vi.mocked(runNow);

async function click() {
  await act(async () => {
    fireEvent.click(screen.getByTestId("today-run-now"));
  });
}

beforeEach(() => {
  auth.current = { role: "Admin", loading: false };
  runNowMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RunNowButton (22.23)", () => {
  it("formats the countdown as m:ss", () => {
    expect(formatCountdown(437)).toBe("7:17");
    expect(formatCountdown(59)).toBe("0:59");
    expect(formatCountdown(0)).toBe("0:00");
  });

  it.each(["Auditor", "Trainer", ""])("is absent for role %j", (role) => {
    auth.current = { role, loading: false };
    render(<RunNowButton />);
    expect(screen.queryByTestId("today-run-now")).toBeNull();
  });

  it("queues once, then disables and counts down from the server's cooldown", async () => {
    vi.useFakeTimers();
    runNowMock.mockResolvedValue({ kind: "enqueued", job_id: "j1", status: "enqueued", cooldown_seconds: 125 });
    const onQueued = vi.fn();
    render(<RunNowButton onQueued={onQueued} />);

    await click();
    await click();
    expect(runNowMock).toHaveBeenCalledTimes(1);
    expect(onQueued).toHaveBeenCalledTimes(1);
    const button = screen.getByTestId("today-run-now");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Run again in 2:05");
    expect(screen.getByRole("status")).toHaveTextContent("Run queued");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(button).toHaveTextContent("Run again in 2:00");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent("Run now");
  });

  it("a 429 shows retry_after_seconds on the button itself — no toast, no alert", async () => {
    runNowMock.mockResolvedValue({ kind: "cooling_down", retry_after_seconds: 437, detail: "Rate limit exceeded." });
    render(<RunNowButton />);
    await click();
    const button = screen.getByTestId("today-run-now");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Run again in 7:17");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("any other failure is shown beside the button, which stays usable", async () => {
    runNowMock.mockRejectedValue(
      new AxiosError("Forbidden", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 403,
        statusText: "",
        data: { detail: "Only Admins can trigger an immediate ATLAS run" },
        headers: {},
        config: { headers: new AxiosHeaders() },
      })
    );
    render(<RunNowButton />);
    await click();
    expect(screen.getByRole("alert")).toHaveTextContent("Only Admins can trigger an immediate ATLAS run");
    expect(screen.getByTestId("today-run-now")).toBeEnabled();
  });
});
