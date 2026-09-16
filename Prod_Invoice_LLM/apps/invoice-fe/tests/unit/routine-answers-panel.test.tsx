/**
 * FE Feature 22 Task 22.27 — routine answers on the Chat Rules settings page.
 *
 * Spec §6: the /settings/chat-rules screen lists the routine answers beside the
 * hand-written rules with an edit affordance; an edit posts
 * `PATCH /today/routine-answers/{key}` ONCE; no second list and no Records tab.
 * Plus: a skipped answer reads "Skipped", a contradicted answer is flagged, editing
 * needs `can_train`, and a `source: "atlas"` chat rule is badged.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), delete: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiClient: api }));

import RoutineAnswersPanel from "@/components/settings/RoutineAnswersPanel";
import ChatRulesPanel from "@/components/settings/ChatRulesPanel";

function answers(data: Record<string, string>, contradictions: string[] = []) {
  api.get.mockImplementation(async (url: string) => {
    if (url === "/today/routine-answers") return { data: { answers: data, contradictions } };
    throw new Error(`unexpected GET ${url}`);
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
});

describe("RoutineAnswersPanel (22.27)", () => {
  it("lists each answer by question, shows skipped ones, and flags contradictions", async () => {
    answers({ payment_run: "month_end", approval_threshold: "100000", collections_owner: "" }, ["payment_run"]);
    render(<RoutineAnswersPanel canTrain />);
    const rows = await screen.findAllByTestId("routine-answer-row");
    expect(rows.map((row) => [row.getAttribute("data-key"), within(row).getByTestId("routine-answer-value").textContent])).toEqual([
      ["payment_run", "Month end"],
      ["approval_threshold", "100000"],
      ["collections_owner", "Skipped"],
    ]);
    expect(within(rows[0]).getByTestId("routine-answer-contradicted")).toBeInTheDocument();
    expect(within(rows[1]).queryByTestId("routine-answer-contradicted")).toBeNull();
  });

  it("an edit posts PATCH once with the new value and re-renders from the response", async () => {
    answers({ payment_run: "month_end" });
    api.patch.mockResolvedValue({ data: { ok: true, key: "payment_run", value: "weekly_run" } });
    render(<RoutineAnswersPanel canTrain />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Payment run" }));
    fireEvent.change(screen.getByLabelText("Payment run"), { target: { value: "weekly_run" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });

    expect(api.patch).toHaveBeenCalledTimes(1);
    expect(api.patch).toHaveBeenCalledWith("/today/routine-answers/payment_run", { value: "weekly_run" });
    expect(screen.getByTestId("routine-answer-value")).toHaveTextContent("Weekly run");
  });

  it("without can_train the answers are read-only", async () => {
    answers({ payment_run: "month_end" });
    render(<RoutineAnswersPanel canTrain={false} />);
    await screen.findAllByTestId("routine-answer-row");
    expect(screen.queryByRole("button", { name: /Edit/ })).toBeNull();
  });

  it("explains an empty state instead of rendering nothing", async () => {
    answers({});
    render(<RoutineAnswersPanel canTrain />);
    expect(await screen.findByTestId("routine-answers-empty")).toBeInTheDocument();
  });

  it("never reads chat rules itself — one list of chat rules, one home", async () => {
    answers({ payment_run: "month_end" });
    render(<RoutineAnswersPanel canTrain />);
    await screen.findAllByTestId("routine-answer-row");
    expect(api.get.mock.calls.map(([url]) => url)).toEqual(["/today/routine-answers"]);
  });
});

describe("ChatRulesPanel marks ATLAS-written rules (22.27)", () => {
  it("badges source=atlas and nothing else", () => {
    render(
      <ChatRulesPanel
        canTrain={false}
        rules={[
          { id: "r1", category: "wrong_direction", pattern: "", ruleText: "Freight lines are not flagged for Kaveri.", enabled: true, source: "atlas" },
          { id: "r2", category: "wrong_direction", pattern: "", ruleText: "Count payables only.", enabled: true, source: "user" },
          { id: "r3", category: "wrong_direction", pattern: "", ruleText: "Legacy rule without source.", enabled: true },
        ]}
      />
    );
    const rows = screen.getAllByTestId("chat-rule-row");
    expect(rows.map((row) => within(row).queryByTestId("chat-rule-source-atlas") !== null)).toEqual([true, false, false]);
  });
});
