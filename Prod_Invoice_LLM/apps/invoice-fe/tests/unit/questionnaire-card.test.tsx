/**
 * FE Feature 22 Task 22.22 — QuestionnaireCard.
 *
 * Spec §6: one question at a time; the chip path and the free-text path post the
 * SAME key; Skip posts and the next question renders; the progress indicator
 * advances; collections_owner offers a user picker with a free-text fallback;
 * defaults come from the server (the fixture uses non-standard defaults, so a
 * hardcoded ₹1,00,000 would fail).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

vi.mock("@/lib/today", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/today")>();
  return {
    ...actual,
    answerQuestionnaire: vi.fn(),
    getRoutineAnswers: vi.fn(),
    listAnswerableUsers: vi.fn(),
  };
});

import QuestionnaireCard from "@/components/today/QuestionnaireCard";
import {
  answerQuestionnaire,
  chipLabel,
  getRoutineAnswers,
  listAnswerableUsers,
  type RoutineQuestion,
} from "@/lib/today";

const answerMock = vi.mocked(answerQuestionnaire);
const answersMock = vi.mocked(getRoutineAnswers);
const usersMock = vi.mocked(listAnswerableUsers);

const PAYMENT_RUN: RoutineQuestion = {
  key: "payment_run",
  prompt: "When do you normally pay your suppliers?",
  chips: ["weekly_run", "on_due_date", "month_end"],
  free_text: true,
  skippable: true,
  answer_kind: "text",
  default_value: null,
};
const OWNER: RoutineQuestion = {
  key: "collections_owner",
  prompt: "Who chases overdue customer payments?",
  chips: ["accounts_team", "owner"],
  free_text: true,
  skippable: true,
  answer_kind: "user",
  default_value: null,
};
const THRESHOLD: RoutineQuestion = {
  key: "approval_threshold",
  prompt: "Above what amount does an invoice need your sign-off?",
  chips: ["50000", "100000"],
  free_text: true,
  skippable: true,
  answer_kind: "currency_amount",
  default_value: "75000",
};

async function save() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));
  });
}

beforeEach(() => {
  answerMock.mockReset();
  answersMock.mockReset();
  usersMock.mockReset();
  answersMock.mockResolvedValue({ answers: { po_before_invoice: "always" }, contradictions: [] });
  usersMock.mockResolvedValue([
    { id: "u1", label: "Priya Shah" },
    { id: "u2", label: "accounts@acme.test" },
  ]);
});

describe("chipLabel", () => {
  it("relabels backend keys for reading only", () => {
    expect(chipLabel("accounts_then_owner_above_threshold")).toBe("Accounts then owner above threshold");
    expect(chipLabel("100000", "currency_amount")).toBe((100000).toLocaleString("en-IN"));
  });
});

describe("QuestionnaireCard (22.22)", () => {
  it("shows one question with its chips, a free-text field and Skip", async () => {
    render(<QuestionnaireCard initialQuestion={PAYMENT_RUN} path="ingest" />);
    expect(await screen.findByTestId("questionnaire-progress")).toHaveTextContent("Question 2");
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(within(screen.getByRole("group", { name: "Suggested answers" })).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Weekly run",
      "On due date",
      "Month end",
    ]);
    expect(screen.getByLabelText("Or in your own words")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument();
  });

  it("the chip path and the free-text path post the same key with the raw value", async () => {
    answerMock.mockResolvedValue({ ok: true, saved_key: "payment_run", has_next: true, next_question: PAYMENT_RUN });
    render(<QuestionnaireCard initialQuestion={PAYMENT_RUN} path="ingest" />);

    fireEvent.click(screen.getByRole("button", { name: "Month end" }));
    await save();
    expect(answerMock).toHaveBeenLastCalledWith({ key: "payment_run", value: "month_end", path: "ingest" });

    fireEvent.change(screen.getByLabelText("Or in your own words"), { target: { value: "Every second Friday" } });
    await save();
    expect(answerMock).toHaveBeenLastCalledWith({ key: "payment_run", value: "Every second Friday", path: "ingest" });
  });

  it("Skip saves an empty answer, the next question replaces it, and progress advances", async () => {
    answerMock.mockResolvedValue({ ok: true, saved_key: "payment_run", has_next: true, next_question: THRESHOLD });
    render(<QuestionnaireCard initialQuestion={PAYMENT_RUN} path="setup" />);
    expect(await screen.findByTestId("questionnaire-progress")).toHaveTextContent("Question 2");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    });
    expect(answerMock).toHaveBeenCalledWith({ key: "payment_run", value: "", path: "setup" });
    expect(screen.getByRole("heading")).toHaveTextContent(THRESHOLD.prompt);
    expect(screen.getByTestId("questionnaire-progress")).toHaveTextContent("Question 3");
  });

  it("pre-fills the server's default_value, not a hardcoded one", async () => {
    render(<QuestionnaireCard initialQuestion={THRESHOLD} path="setup" />);
    expect(screen.getByLabelText("Or in your own words")).toHaveValue(75000);
  });

  it("collections_owner offers a user picker and keeps free text as a fallback", async () => {
    answerMock.mockResolvedValue({ ok: true, saved_key: "collections_owner", has_next: true, next_question: OWNER });
    render(<QuestionnaireCard initialQuestion={OWNER} path="setup" />);
    const picker = await screen.findByLabelText("Pick a person");
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose…", "Priya Shah", "accounts@acme.test"]);

    fireEvent.change(picker, { target: { value: "Priya Shah" } });
    await save();
    expect(answerMock).toHaveBeenLastCalledWith({ key: "collections_owner", value: "Priya Shah", path: "setup" });

    fireEvent.change(screen.getByLabelText("Or type a name"), { target: { value: "Ravi (not on the app yet)" } });
    await save();
    expect(answerMock).toHaveBeenLastCalledWith({ key: "collections_owner", value: "Ravi (not on the app yet)", path: "setup" });
  });

  it("without a user list, collections_owner is free text only", async () => {
    usersMock.mockResolvedValue([]);
    render(<QuestionnaireCard initialQuestion={OWNER} path="setup" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByLabelText("Pick a person")).toBeNull();
    expect(screen.getByLabelText("Or type a name")).toBeInTheDocument();
  });

  it("the last answer completes the card once", async () => {
    answerMock.mockResolvedValue({ ok: true, saved_key: "approval_threshold", has_next: false, next_question: null });
    const onComplete = vi.fn();
    render(<QuestionnaireCard initialQuestion={THRESHOLD} path="setup" onComplete={onComplete} />);
    await save();
    expect(screen.getByTestId("questionnaire-complete")).toBeInTheDocument();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("a failed save is shown and the question stays", async () => {
    answerMock.mockRejectedValue(new Error("network down"));
    render(<QuestionnaireCard initialQuestion={THRESHOLD} path="setup" />);
    await save();
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save this answer");
    expect(screen.getByRole("heading")).toHaveTextContent(THRESHOLD.prompt);
  });
});
