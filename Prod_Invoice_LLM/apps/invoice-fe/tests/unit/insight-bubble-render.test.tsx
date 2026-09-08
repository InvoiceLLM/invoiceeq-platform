// =============================================================================
// FILE: tests/unit/insight-bubble-render.test.tsx
// FEATURE: FE Feature 21 — the rendered bubble (tasks 21.6 / 21.2 / 21.4 / 21.8).
//
// Proves the §8.3 anatomy and, just as importantly, the ONE rule the whole
// feature turns on: information only (BE Gap 492). The last test in this file
// fails if a pin, hold, dispute or mark-paid control ever appears in the bubble.
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

const ATTACHMENT_ID = "33333333-3333-3333-3333-333333333333";
const MESSAGE_ID = "11111111-1111-1111-1111-111111111111";
const ROW_ID = "aaaaaaaa-0000-0000-0000-000000000001";

function block(overrides: Partial<InsightBlock> = {}): InsightBlock {
  return {
    stage: "sync",
    doc_type: "PURCHASE_ORDER",
    doc_type_label: "purchase order",
    attachment_id: ATTACHMENT_ID,
    currency: "INR",
    verdict: "Check the Shree Packaging invoice — it bills more than this purchase order agreed.",
    verdict_source: "template",
    cards: [],
    figures: {},
    generated_at: "2026-09-08T10:15:00Z",
    actions: [
      { action: "note", label: "Add a note", status: "ACTED", outcome: "note" },
      { action: "discuss", label: "Discuss", endpoint: "discuss" },
      { action: "dismiss", label: "Dismiss", status: "DISMISSED", outcome: "dismissed" },
    ],
    checks_not_run: [{ card: "bank_match", reason: "no statement on file" }],
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
      {
        finding_key: "duplicate_billing:INV-1002",
        card: "duplicate_billing",
        title: "INV-1002 repeats a line already billed",
        impact_amount: 4100,
        currency: "INR",
        confidence: "med",
        confidence_reason: "descriptions match",
        evidence: { invoice_number: "INV-1002" },
      },
      {
        finding_key: "delivery_vs_order:INV-1003",
        card: "delivery_vs_order",
        title: "INV-1003 bills 40 units but 30 were delivered",
        impact_amount: null,
        confidence: "low",
        confidence_reason: "the delivery note has no unit",
        evidence: { invoice_number: "INV-1003" },
      },
      {
        finding_key: "price_drift:INV-1004",
        card: "price_drift",
        title: "INV-1004 charges more per unit than the last order",
        impact_amount: 900,
        currency: "INR",
        confidence: "med",
        confidence_reason: "one earlier order to compare",
        evidence: { invoice_number: "INV-1004" },
      },
    ],
    ...overrides,
  };
}

const openRow = {
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
  created_at: "2026-09-08T10:15:00Z",
  updated_at: "2026-09-08T10:15:00Z",
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  get.mockResolvedValue({ data: [openRow] });
  post.mockResolvedValue({ data: { ...openRow, status: "ACTED", is_open: false } });
});

describe("21.6 — bubble anatomy (§8.3)", () => {
  it("renders the verdict, three findings, the collapsed rest and the not-checked line", async () => {
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);

    expect(screen.getByTestId("insight-verdict").textContent).toContain(
      "bills more than this purchase order agreed"
    );
    expect(screen.getAllByTestId("insight-finding")).toHaveLength(3);
    expect(screen.getByTestId("insight-more-findings").textContent).toContain("1 more finding");
    expect(screen.queryByTestId("insight-hidden-findings")).toBeNull();
    expect(screen.getByTestId("insight-checks-not-run").textContent).toContain(
      "Not checked: bank match (no statement on file)"
    );
    await waitFor(() => expect(get).toHaveBeenCalled());
  });

  it("expands the collapsed findings on click", async () => {
    const user = userEvent.setup();
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await user.click(screen.getByTestId("insight-more-findings"));
    expect(screen.getByTestId("insight-hidden-findings")).toBeTruthy();
    expect(screen.getAllByTestId("insight-finding")).toHaveLength(4);
  });

  it("shows currency impact with tabular numerals, and none where there is no amount", async () => {
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    const impacts = screen.getAllByTestId("insight-finding-impact");
    // Third finding has `impact_amount: null` — it must not render a zero.
    expect(impacts).toHaveLength(2);
    expect(impacts[0].className).toContain("tabular-nums");
    expect(impacts[0].textContent).toContain("23,200");
  });

  it("chips confidence in plain words with its reason, never the raw grade", async () => {
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    const chips = screen.getAllByTestId("insight-confidence-chip");
    expect(chips[0].getAttribute("data-confidence")).toBe("high");
    expect(chips[0].textContent).toContain("Sure");
    expect(chips[0].textContent).toContain("both documents state a total");
    expect(chips[1].textContent).not.toMatch(/\bmed\b/);
  });

  it("shows evidence as plain text, never a link (founder 2026-09-08)", async () => {
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    const chips = screen.getAllByTestId("insight-evidence");
    expect(chips[0].textContent).toBe("INV-1001");
    expect(chips[0].tagName).toBe("SPAN");
    expect(screen.queryAllByTestId("insight-evidence-link")).toHaveLength(0);
  });

  it("renders nothing at all for an empty block", () => {
    const { container } = render(
      <InsightBubble
        block={block({ verdict: "", findings: [], checks_not_run: [] })}
        messageId={MESSAGE_ID}
      />
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("21.6 — information only (BE Gap 492)", () => {
  it("offers no pin and no control that changes an invoice", async () => {
    const { container } = render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    const text = container.textContent?.toLowerCase() ?? "";
    for (const banned of ["pin", "keep this", "hold", "dispute", "mark paid", "mark as paid"]) {
      expect(text).not.toContain(banned);
    }
    expect(screen.queryByTestId("insight-action-pin")).toBeNull();
    expect(screen.queryByTestId("insight-action-hold")).toBeNull();
  });

  it("uses no internal vocabulary in any string", async () => {
    const { container } = render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    const text = container.textContent?.toLowerCase() ?? "";
    for (const term of ["tier", "delta", "3-way", "three-way"]) {
      expect(text).not.toContain(term);
    }
  });

  it("renders only the three approved actions", async () => {
    render(<InsightBubble block={block()} messageId={MESSAGE_ID} />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.getByTestId("insight-action-discuss")).toBeTruthy();
    expect(screen.getByTestId("insight-action-note")).toBeTruthy();
    expect(screen.getByTestId("insight-action-dismiss")).toBeTruthy();
  });
});
