// =============================================================================
// FILE: tests/unit/action-line.test.tsx
// FEATURE: FE Feature 22 Task 22.19 — ActionLine on Today
// =============================================================================

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React from "react";
import * as todayApi from "@/lib/today";
import ActionLine from "@/components/today/ActionLine";

const authMock = vi.hoisted(() => ({ role: "Admin", loading: false }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => authMock,
}));

describe("ActionLine (Task 22.19)", () => {
  let confirmSpy: any;
  let dismissSpy: any;

  const mockLine: todayApi.TodayLineModel = {
    key: "finding-f-101",
    kind: "action",
    text: "Inbound mailbox is not configured for automatic invoice ingestion.",
    detail: "Set up the default email address to start receiving supplier PDFs.",
    itemId: "f-101",
    meta: {
      action: "setup_inbound_email",
      action_label: "Set Up Inbound Mailbox",
    },
  };

  beforeEach(() => {
    authMock.role = "Admin";

    confirmSpy = vi.spyOn(todayApi, "confirmAction").mockResolvedValue({
      ok: true,
      result: { status: "configured" },
    });

    dismissSpy = vi.spyOn(todayApi, "dismissTodayItem").mockResolvedValue({
      ok: true,
      item_id: "f-101",
      dismissed: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders Confirm and Dismiss buttons for an allowed role (Admin)", () => {
    render(<ActionLine line={mockLine} />);

    expect(screen.getByText("Inbound mailbox is not configured for automatic invoice ingestion.")).toBeInTheDocument();
    expect(screen.getByText("Set up the default email address to start receiving supplier PDFs.")).toBeInTheDocument();

    const confirmBtn = screen.getByTestId("action-confirm-btn");
    expect(confirmBtn).toBeInTheDocument();
    expect(confirmBtn).toHaveTextContent("Set Up Inbound Mailbox");

    const dismissBtn = screen.getByTestId("action-dismiss-btn");
    expect(dismissBtn).toBeInTheDocument();
    expect(dismissBtn).toHaveTextContent("Dismiss");
  });

  it("Confirm button is ABSENT for a disallowed role (Auditor)", () => {
    authMock.role = "Auditor";

    render(<ActionLine line={mockLine} />);

    expect(screen.queryByTestId("action-confirm-btn")).not.toBeInTheDocument();
    // Dismiss button is still present on every line
    expect(screen.getByTestId("action-dismiss-btn")).toBeInTheDocument();
  });

  it("Confirm button is ABSENT for Trainer role", () => {
    authMock.role = "Trainer";

    render(<ActionLine line={mockLine} />);

    expect(screen.queryByTestId("action-confirm-btn")).not.toBeInTheDocument();
    expect(screen.getByTestId("action-dismiss-btn")).toBeInTheDocument();
  });

  it("allowed role clicks Confirm: calls confirmAction once and line disappears", async () => {
    render(<ActionLine line={mockLine} />);

    const confirmBtn = screen.getByTestId("action-confirm-btn");
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledTimes(1);
      expect(confirmSpy).toHaveBeenCalledWith("f-101");
    });

    // Line removed after confirmed
    await waitFor(() => {
      expect(screen.queryByTestId("today-line-action")).not.toBeInTheDocument();
    });
  });

  it("Dismiss calls dismissTodayItem once and the line disappears", async () => {
    render(<ActionLine line={mockLine} />);

    const dismissBtn = screen.getByTestId("action-dismiss-btn");
    fireEvent.click(dismissBtn);

    await waitFor(() => {
      expect(dismissSpy).toHaveBeenCalledTimes(1);
      expect(dismissSpy).toHaveBeenCalledWith("f-101");
    });

    await waitFor(() => {
      expect(screen.queryByTestId("today-line-action")).not.toBeInTheDocument();
    });
  });

  it("forced post returning 403 renders error directly on the line", async () => {
    confirmSpy.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 403,
        data: { detail: "Role 'Auditor' is not permitted to execute 'setup_inbound_email'" },
      },
    });

    render(<ActionLine line={mockLine} />);

    const confirmBtn = screen.getByTestId("action-confirm-btn");
    fireEvent.click(confirmBtn);

    const errorAlert = await screen.findByRole("alert");
    expect(errorAlert).toBeInTheDocument();
    expect(errorAlert).toHaveTextContent("Role 'Auditor' is not permitted to execute 'setup_inbound_email'");

    // Line remains visible so user can see the error
    expect(screen.getByTestId("today-line-action")).toBeInTheDocument();
  });
});
