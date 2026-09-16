/**
 * FE Feature 22 Task 22.12 — ReviewCard.
 *
 * Spec §6: `Accept computed` posts to the same endpoint the review page did, with
 * the same body — asserted against a fixture RECORDED from the review page's own
 * AlertConsole, not hand-written. Plus: `Accept printed` matches the plain
 * Dismiss; the computed column never parses the alert message (no
 * `computed_value` -> "Not sent yet" and the button is disabled); `Tell me why`
 * seeds and never sends; and /ask?invoice= pins the card in a conversation.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiClient: api }));

import ReviewCard, { type ReviewAlert } from "@/components/chat/cards/ReviewCard";
import AlertConsole from "@/components/audit/AlertConsole";

const TOTAL_ALERT: ReviewAlert = {
  type: "total_mismatch",
  message: "Subtotal (1000.00) + tax (180.00) does not match grand total (1200.00)",
  field: "grand_total",
};
const DUP_ALERT: ReviewAlert = { type: "duplicate", message: "Possible duplicate of INV-7" };

function invoice(alerts: ReviewAlert[], extra: Record<string, unknown> = {}) {
  return {
    id: "inv-1",
    status: "AUDIT_REQUIRED",
    vendor_name: "Rajesh Traders",
    invoice_number: "INV-1041",
    grand_total: 1200,
    currency: "INR",
    flow_direction: "INBOUND",
    sa_alerts: alerts,
    ...extra,
  };
}

function serve(data: unknown) {
  api.get.mockImplementation(async (url: string) => {
    if (url === "/invoices/inv-1") return { data };
    throw new Error(`unexpected GET ${url}`);
  });
}

/** What the review page's per-alert Dismiss sends, with the auditor's correction staged. */
async function recordReviewPageBody(alert: ReviewAlert, corrections?: Record<string, string>) {
  api.put.mockResolvedValue({ data: {} });
  const { unmount } = render(
    <AlertConsole invoiceId="inv-1" alerts={[alert]} currentStatus="AUDIT_REQUIRED" onAlertsChange={vi.fn()} corrections={corrections} />
  );
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/ }));
  });
  const call = api.put.mock.calls.at(-1);
  unmount();
  api.put.mockReset();
  return call;
}

beforeEach(() => {
  api.get.mockReset();
  api.put.mockReset();
});

describe("ReviewCard (22.12)", () => {
  it("shows the flag with printed and computed side by side, printed from the invoice row", async () => {
    serve(invoice([{ ...TOTAL_ALERT, computed_value: "1180.00" }]));
    render(<ReviewCard invoiceId="inv-1" />);
    const flag = await screen.findByTestId("review-flag");
    expect(flag).toHaveAttribute("data-field", "grand_total");
    expect(within(flag).getByTestId("review-flag-printed")).toHaveTextContent("1,200.00");
    expect(within(flag).getByTestId("review-flag-computed")).toHaveTextContent("1180.00");
    expect(screen.getByTestId("review-card-thumbnail")).toHaveAttribute("src", expect.stringContaining("/api/invoices/inv-1/pdf"));
  });

  it("Accept computed posts the review page's own endpoint and body (recorded fixture)", async () => {
    const recorded = await recordReviewPageBody(TOTAL_ALERT, { grand_total: "1180.00" });
    serve(invoice([{ ...TOTAL_ALERT, computed_value: "1180.00" }]));
    api.put.mockResolvedValue({ data: {} });
    render(<ReviewCard invoiceId="inv-1" />);
    const button = await screen.findByRole("button", { name: "Accept computed" });
    await act(async () => {
      fireEvent.click(button);
    });
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.put.mock.calls[0]).toEqual(recorded);
    expect(screen.getByTestId("review-card-clear")).toBeInTheDocument();
  });

  it("Accept printed posts the review page's plain Dismiss body (recorded fixture)", async () => {
    const recorded = await recordReviewPageBody(TOTAL_ALERT);
    serve(invoice([TOTAL_ALERT, DUP_ALERT]));
    api.put.mockResolvedValue({ data: {} });
    render(<ReviewCard invoiceId="inv-1" />);
    const [first] = await screen.findAllByTestId("review-flag");
    await act(async () => {
      fireEvent.click(within(first).getByRole("button", { name: "Accept printed" }));
    });
    expect(api.put.mock.calls).toEqual([recorded]);
    expect(screen.getAllByTestId("review-flag")).toHaveLength(1);
  });

  it("never derives the computed value: without computed_value it reads 'Not sent yet' and cannot be accepted", async () => {
    serve(invoice([TOTAL_ALERT]));
    render(<ReviewCard invoiceId="inv-1" />);
    const flag = await screen.findByTestId("review-flag");
    expect(within(flag).getByTestId("review-flag-computed")).toHaveTextContent("Not sent yet");
    const accept = within(flag).getByRole("button", { name: "Accept computed" });
    expect(accept).toBeDisabled();
    fireEvent.click(accept);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("an alert on no correctable field has no printed/computed row and no Accept computed", async () => {
    serve(invoice([{ ...DUP_ALERT, computed_value: "x" }]));
    render(<ReviewCard invoiceId="inv-1" />);
    const flag = await screen.findByTestId("review-flag");
    expect(within(flag).queryByTestId("review-flag-printed")).toBeNull();
    expect(within(flag).getByRole("button", { name: "Accept computed" })).toBeDisabled();
  });

  it("Tell me why seeds the question and sends nothing", async () => {
    serve(invoice([TOTAL_ALERT]));
    const seed = vi.fn();
    render(<ReviewCard invoiceId="inv-1" onTellMeWhy={seed} />);
    fireEvent.click(await screen.findByRole("button", { name: "Tell me why" }));
    expect(seed).toHaveBeenCalledTimes(1);
    expect(seed.mock.calls[0][0]).toContain("INV-1041");
    expect(seed.mock.calls[0][0]).toContain(TOTAL_ALERT.message);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("a failed save keeps the flag and shows the server's reason", async () => {
    serve(invoice([TOTAL_ALERT]));
    api.put.mockRejectedValue({ response: { data: { detail: "Invoice not found or access denied." } } });
    render(<ReviewCard invoiceId="inv-1" />);
    const button = await screen.findByRole("button", { name: "Accept printed" });
    await act(async () => {
      fireEvent.click(button);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Invoice not found or access denied.");
    expect(screen.getByTestId("review-flag")).toBeInTheDocument();
  });

  it("an outgoing invoice points to the outgoing review page instead", async () => {
    serve(invoice([TOTAL_ALERT], { flow_direction: "OUTBOUND" }));
    render(<ReviewCard invoiceId="inv-1" />);
    const note = await screen.findByTestId("review-card-outbound");
    expect(within(note).getByRole("link")).toHaveAttribute("href", "/invoices/outbound-review/inv-1");
    expect(screen.queryByTestId("review-flag")).toBeNull();
  });
});
