// =============================================================================
// FILE: tests/unit/insight-actions.test.tsx
// FEATURE: FE Feature 21 tasks 21.8 (Discuss / note / dismiss / the History
//          chip) and 21.4 (thumbs + correction dialog).
//
// The assertions are deliberately about WHICH CALL IS MADE, not about what the
// button looks like: the one rule this feature cannot get wrong is that Discuss
// is a READ that seeds the composer, and that note/dismiss write only the
// finding's own lifecycle row (BE Gap 492 — nothing touches an invoice).
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { InsightBlock } from "@/lib/chatInsights";

const get = vi.fn();
const post = vi.fn();

vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    get: (...args: any[]) => get(...args),
    post: (...args: any[]) => post(...args),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import InsightBubble from "@/components/chat/InsightBubble";
import OpenFindingsChip from "@/components/insights/OpenFindingsChip";

const ATTACHMENT_ID = "33333333-3333-3333-3333-333333333333";
const MESSAGE_ID = "11111111-1111-1111-1111-111111111111";
const ROW_ID = "aaaaaaaa-0000-0000-0000-000000000001";

const row = {
  id: ROW_ID,
  attachment_id: ATTACHMENT_ID,
  doc_type: "PURCHASE_ORDER",
  card: "agreed_vs_billed",
  finding_key: "agreed_vs_billed:INV-1001",
  title: "INV-1001 bills more than this purchase order agreed",
  impact_amount: 23200,
  currency: "INR",
  confidence: "high",
  status: "OPEN",
  is_open: true,
  outcome: null,
  created_at: "2026-09-08T10:15:00Z",
  updated_at: "2026-09-08T10:15:00Z",
};

const block: InsightBlock = {
  stage: "sync",
  doc_type: "PURCHASE_ORDER",
  attachment_id: ATTACHMENT_ID,
  currency: "INR",
  verdict: "Check the Shree Packaging invoice — it bills more than this purchase order agreed.",
  cards: [],
  figures: {},
  generated_at: "2026-09-08T10:15:00Z",
  actions: [
    { action: "note", label: "Add a note", status: "ACTED", outcome: "note" },
    { action: "discuss", label: "Discuss", endpoint: "discuss" },
    { action: "dismiss", label: "Dismiss", status: "DISMISSED", outcome: "dismissed" },
  ],
  checks_not_run: [],
  findings: [
    {
      finding_key: "agreed_vs_billed:INV-1001",
      card: "agreed_vs_billed",
      title: "INV-1001 bills more than this purchase order agreed",
      impact_amount: 23200,
      currency: "INR",
      confidence: "high",
      confidence_reason: "both documents state a total",
      evidence: { invoice_number: "INV-1001" },
    },
  ],
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  get.mockImplementation((url: string) => {
    if (url.endsWith("/discuss")) {
      return Promise.resolve({
        data: { seed_text: "About this finding (INR 23,200.00): INV-1001 bills more — what should I do?" },
      });
    }
    return Promise.resolve({ data: [row] });
  });
  post.mockResolvedValue({ data: { ...row, status: "ACTED", is_open: false, outcome: "note" } });
});

describe("21.8 — Discuss seeds the composer and never sends", () => {
  it("reads the seed endpoint and hands the text up, with no POST at all", async () => {
    const user = userEvent.setup();
    const onDiscussSeed = vi.fn();
    render(
      <InsightBubble block={block} messageId={MESSAGE_ID} onDiscussSeed={onDiscussSeed} />
    );
    await waitFor(() => expect(get).toHaveBeenCalled());

    await user.click(screen.getByTestId("insight-action-discuss"));

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(`/chat/insights/${ROW_ID}/discuss`)
    );
    expect(onDiscussSeed).toHaveBeenCalledWith(
      expect.stringContaining("what should I do?")
    );
    // The one assertion that matters: Discuss wrote nothing.
    expect(post).not.toHaveBeenCalled();
  });
});

describe("21.8 — Add a note and Dismiss call the transition endpoint", () => {
  it("records ACTED + note with the text the user typed", async () => {
    const user = userEvent.setup();
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(screen.getByTestId("insight-action-note")).toBeEnabled());

    await user.click(screen.getByTestId("insight-action-note"));
    await user.type(screen.getByTestId("insight-note-input"), "Called the supplier");
    await user.click(screen.getByTestId("insight-note-save"));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/chat/insights/${ROW_ID}/transition`, {
        status: "ACTED",
        outcome: "note",
        note: "Called the supplier",
      })
    );
    expect(await screen.findByTestId("insight-outcome")).toBeTruthy();
  });

  it("records DISMISSED + dismissed, and never posts to an invoice route", async () => {
    const user = userEvent.setup();
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(screen.getByTestId("insight-action-dismiss")).toBeEnabled());

    await user.click(screen.getByTestId("insight-action-dismiss"));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/chat/insights/${ROW_ID}/transition`, {
        status: "DISMISSED",
        outcome: "dismissed",
      })
    );
    for (const [url] of post.mock.calls) {
      expect(String(url)).not.toContain("/invoices");
    }
    expect(screen.getByTestId("insight-outcome").textContent).toContain("dismissed");
  });

  it("keeps the two write actions disabled until the lifecycle row resolves", () => {
    get.mockReturnValue(new Promise(() => {})); // never settles
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    expect(screen.getByTestId("insight-action-note")).toBeDisabled();
    expect(screen.getByTestId("insight-action-dismiss")).toBeDisabled();
    // Discuss needs no row — it falls back to the finding's own text.
    expect(screen.getByTestId("insight-action-discuss")).toBeEnabled();
  });

  it("shows a closed finding as closed on first paint instead of offering it again", async () => {
    get.mockResolvedValue({
      data: [{ ...row, status: "DISMISSED", is_open: false, outcome: "dismissed" }],
    });
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    expect(await screen.findByTestId("insight-outcome")).toBeTruthy();
    expect(screen.queryByTestId("insight-action-dismiss")).toBeNull();
  });
});

describe("21.4 — thumbs and the correction dialog", () => {
  it("sends an up-vote straight away with the finding it is about", async () => {
    const user = userEvent.setup();
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());

    await user.click(screen.getByTestId("insight-thumbs-up"));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/chat/messages/${MESSAGE_ID}/insight-feedback`, {
        vote: "up",
        card: "agreed_vs_billed",
        finding_key: "agreed_vs_billed:INV-1001",
        insight_id: ROW_ID,
      })
    );
  });

  it("opens the dialog on thumbs-down and posts the reason and the correction", async () => {
    const user = userEvent.setup();
    render(<InsightBubble block={block} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());

    await user.click(screen.getByTestId("insight-thumbs-down"));
    expect(screen.getByTestId("insight-correction-dialog")).toBeTruthy();
    // No vote is written by merely opening it.
    expect(post).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("insight-correction-reason-wrong_amount"));
    await user.type(screen.getByTestId("insight-correction-text"), "The PO was revised");
    await user.click(screen.getByTestId("insight-correction-submit"));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/chat/messages/${MESSAGE_ID}/insight-feedback`, {
        vote: "down",
        reason: "wrong_amount",
        card: "agreed_vs_billed",
        finding_key: "agreed_vs_billed:INV-1001",
        insight_id: ROW_ID,
        corrected_text: "The PO was revised",
      })
    );
    await waitFor(() => expect(screen.queryByTestId("insight-correction-dialog")).toBeNull());
  });
});

describe("21.8 — the History screen's open-findings chip", () => {
  it("asks for open findings only and lists them on click", async () => {
    const user = userEvent.setup();
    render(<OpenFindingsChip />);

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/chat/insights", {
        params: { status: "OPEN", limit: 100 },
      })
    );
    expect(screen.getByTestId("open-findings-chip").textContent).toContain("1 open finding");

    await user.click(screen.getByTestId("open-findings-chip"));
    expect(screen.getAllByTestId("open-finding-row")).toHaveLength(1);
  });

  it("renders nothing when there is nothing open (also the flag-off shape)", async () => {
    get.mockResolvedValue({ data: [] });
    const { container } = render(<OpenFindingsChip />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when the read fails, rather than an error on this screen", async () => {
    get.mockRejectedValue(new Error("boom"));
    const { container } = render(<OpenFindingsChip />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});
