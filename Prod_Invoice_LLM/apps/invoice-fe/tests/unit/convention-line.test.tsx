// =============================================================================
// FILE: tests/unit/convention-line.test.tsx
// FEATURE: FE Feature 22 Task 22.18 — ConventionLine on Today
// =============================================================================

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React from "react";
import * as todayApi from "@/lib/today";
import ConventionLine from "@/components/today/ConventionLine";

const pushSpy = vi.fn();
const replaceSpy = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushSpy,
    replace: replaceSpy,
  }),
}));

describe("ConventionLine (Task 22.18)", () => {
  let acceptSpy: any;
  let editSpy: any;
  let rejectSpy: any;

  const mockProposal: todayApi.ConventionProposal = {
    id: "prop-42",
    kind: "early_payment_discount",
    title: "Always take 2% net 10 for Acme Corp",
    description: "Acme offers 2% 10 net 30 on all invoices.",
    suggested_rule: "If vendor is Acme Corp and terms include 2/10 net 30, schedule payment within 10 days.",
    evidence: { vendor: "Acme Corp", discount: 0.02 },
  };

  const mockLine: todayApi.TodayLineModel = {
    key: "proposal-prop-42",
    kind: "proposal",
    text: "Always take 2% net 10 for Acme Corp",
    detail: "Acme offers 2% 10 net 30 on all invoices.",
    proposal: mockProposal,
  };

  beforeEach(() => {
    pushSpy.mockClear();
    replaceSpy.mockClear();

    acceptSpy = vi.spyOn(todayApi, "acceptConvention").mockResolvedValue({
      ok: true,
      rule_id: "rule-prop-42",
      rule_text: mockProposal.suggested_rule,
    });

    editSpy = vi.spyOn(todayApi, "editConvention").mockResolvedValue({
      ok: true,
      rule_id: "rule-prop-42-edited",
      rule_text: "Modified rule",
    });

    rejectSpy = vi.spyOn(todayApi, "rejectConvention").mockResolvedValue({
      ok: true,
      suppressed_kind: "early_payment_discount",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders proposal title, description, suggested rule and action buttons", () => {
    render(<ConventionLine line={mockLine} />);

    expect(screen.getByText("Always take 2% net 10 for Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("Acme offers 2% 10 net 30 on all invoices.")).toBeInTheDocument();
    expect(screen.getByTestId("convention-suggested-rule")).toHaveTextContent(mockProposal.suggested_rule);
    expect(screen.getByTestId("convention-accept-btn")).toBeInTheDocument();
    expect(screen.getByTestId("convention-edit-btn")).toBeInTheDocument();
    expect(screen.getByTestId("convention-reject-btn")).toBeInTheDocument();
  });

  it("Accept calls acceptConvention once, re-renders with active rule, and does NOT navigate", async () => {
    render(<ConventionLine line={mockLine} />);

    const acceptBtn = screen.getByTestId("convention-accept-btn");
    fireEvent.click(acceptBtn);

    await waitFor(() => {
      expect(acceptSpy).toHaveBeenCalledTimes(1);
      expect(acceptSpy).toHaveBeenCalledWith("prop-42");
    });

    // Re-renders in place with active banner
    await waitFor(() => {
      expect(screen.getByTestId("convention-accepted-banner")).toBeInTheDocument();
      expect(screen.getByTestId("convention-accepted-banner")).toHaveTextContent(mockProposal.suggested_rule);
    });

    // Action buttons are no longer present
    expect(screen.queryByTestId("convention-accept-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("convention-edit-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("convention-reject-btn")).not.toBeInTheDocument();

    // Spec constraint: Zero navigation
    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it("Edit opens inline textarea, submits edited rule, and re-renders in place without navigating", async () => {
    render(<ConventionLine line={mockLine} />);

    const editBtn = screen.getByTestId("convention-edit-btn");
    fireEvent.click(editBtn);

    // Textarea is shown with initial rule
    const textarea = screen.getByTestId("convention-rule-input") as HTMLTextAreaElement;
    expect(textarea.value).toBe(mockProposal.suggested_rule);

    const editedRuleText = "Modified: Always pay Acme in 7 days for 2% discount.";
    fireEvent.change(textarea, { target: { value: editedRuleText } });

    const saveBtn = screen.getByTestId("convention-save-btn");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(editSpy).toHaveBeenCalledTimes(1);
      expect(editSpy).toHaveBeenCalledWith("prop-42", editedRuleText, "tenant_chat_rule");
    });

    await waitFor(() => {
      expect(screen.getByTestId("convention-accepted-banner")).toBeInTheDocument();
      expect(screen.getByTestId("convention-accepted-banner")).toHaveTextContent(editedRuleText);
    });

    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it("Cancel in edit mode restores initial state", () => {
    render(<ConventionLine line={mockLine} />);

    fireEvent.click(screen.getByTestId("convention-edit-btn"));
    expect(screen.getByTestId("convention-rule-input")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("convention-cancel-btn"));
    expect(screen.queryByTestId("convention-rule-input")).not.toBeInTheDocument();
    expect(screen.getByTestId("convention-suggested-rule")).toBeInTheDocument();
  });

  it("Reject calls rejectConvention once, removes the line, and does NOT navigate", async () => {
    const { container } = render(<ConventionLine line={mockLine} />);

    const rejectBtn = screen.getByTestId("convention-reject-btn");
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(rejectSpy).toHaveBeenCalledTimes(1);
      expect(rejectSpy).toHaveBeenCalledWith("prop-42");
    });

    // Entire line removes itself from the DOM
    await waitFor(() => {
      expect(screen.queryByTestId("today-line-proposal")).not.toBeInTheDocument();
    });

    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it("displays error message inline when API call fails", async () => {
    acceptSpy.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 500, data: { detail: "Failed to persist rule in database" } },
    });

    render(<ConventionLine line={mockLine} />);

    fireEvent.click(screen.getByTestId("convention-accept-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Failed to persist rule in database");

    // Line remains visible and button re-enabled
    expect(screen.getByTestId("convention-accept-btn")).toBeEnabled();
  });
});
