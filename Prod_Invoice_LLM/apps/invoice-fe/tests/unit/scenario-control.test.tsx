/**
 * FE Feature 22 Task 22.20 — ScenarioControl.
 *
 * Spec §6: a scenario change posts ONCE and re-renders the RETURNED line, per
 * currency, with no blended total. The fixture's sentences are the backend's —
 * nothing in the component may compute or combine the per-currency figures.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

vi.mock("@/lib/today", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/today")>();
  return { ...actual, runScenario: vi.fn() };
});

import ScenarioControl, { SCENARIO_HORIZON_DAYS } from "@/components/today/ScenarioControl";
import { runScenario } from "@/lib/today";

const runMock = vi.mocked(runScenario);

function fill(who: string, days: string) {
  fireEvent.click(screen.getByTestId("scenario-open"));
  fireEvent.change(screen.getByLabelText("Who"), { target: { value: who } });
  fireEvent.change(screen.getByLabelText("Days late"), { target: { value: days } });
}

beforeEach(() => {
  runMock.mockReset();
});

describe("ScenarioControl (22.20)", () => {
  it("posts one change and renders the returned sentence per currency, never a blended total", async () => {
    runMock.mockResolvedValue({
      ok: true,
      currencies: ["INR", "USD"],
      cash_position_by_currency: { INR: 690000, USD: 18250 },
      runway_days_by_currency: { INR: 9, USD: 40 },
      certain_summary: { INR: "₹6,90,000 covers 9 days of committed payments.", USD: "$18,250 covers 40 days." },
      tiers_summary: {},
    });
    render(<ScenarioControl />);
    fill("Kaveri Traders", "20");

    const submit = screen.getByRole("button", { name: /Recalculate/ });
    await act(async () => {
      fireEvent.click(submit);
      fireEvent.click(submit);
    });

    expect(runMock).toHaveBeenCalledTimes(1);
    expect(runMock).toHaveBeenCalledWith("cash", {
      change: { counterparty: "Kaveri Traders", delay_days: 20 },
      horizon_days: SCENARIO_HORIZON_DAYS,
    });
    const lines = screen.getAllByTestId("scenario-line");
    expect(lines.map((l) => [l.getAttribute("data-currency"), l.textContent])).toEqual([
      ["INR", "₹6,90,000 covers 9 days of committed payments."],
      ["USD", "$18,250 covers 40 days."],
    ]);
    expect(screen.getByTestId("scenario-result").textContent).not.toMatch(/total|708,250|7,08,250/i);
    expect(screen.getByTestId("scenario-result")).toHaveTextContent("If Kaveri Traders pays 20 days late");
  });

  it("cannot run without a counterparty and a whole, non-zero number of days", () => {
    render(<ScenarioControl />);
    fill("", "20");
    expect(screen.getByRole("button", { name: /Recalculate/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Who"), { target: { value: "Kaveri" } });
    fireEvent.change(screen.getByLabelText("Days late"), { target: { value: "2.5" } });
    expect(screen.getByRole("button", { name: /Recalculate/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Days late"), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: /Recalculate/ })).toBeDisabled();
    expect(runMock).not.toHaveBeenCalled();
  });

  it("shows a failure inline and keeps the form", async () => {
    runMock.mockRejectedValue(new Error("network down"));
    render(<ScenarioControl />);
    fill("Kaveri", "20");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Recalculate/ }));
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not run this scenario");
    expect(screen.getByLabelText("Who")).toHaveValue("Kaveri");
  });
});
