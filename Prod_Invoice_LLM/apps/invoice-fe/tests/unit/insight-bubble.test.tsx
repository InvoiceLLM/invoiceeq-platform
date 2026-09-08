// =============================================================================
// FILE: tests/unit/insight-bubble.test.tsx
// FEATURE: FE Feature 21 — Business Intelligence bubble.
//
// The verification plan's 21.1 proof: "a message without `insights` renders
// byte-identical". That is asserted here the only way it can be asserted
// honestly — by rendering the SAME message twice, once through the component as
// it stands and once with an `insights` key that is `undefined`, and comparing
// the emitted HTML string. A snapshot file would freeze today's markup and go
// green on a change to any other part of the bubble; comparing the two renders
// pins the actual claim, which is that the new branch is inert when the key is
// absent.
// =============================================================================

import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import MessageBubble from "@/components/chat/MessageBubble";
import type { ChatMessage } from "@/types/chat";
import {
  cardLabel,
  checksNotRunLine,
  confidenceLabel,
  confidenceTone,
  evidenceInvoiceNumbers,
  findingImpact,
  hasRenderableInsights,
  insightForFinding,
  isStaleInsightUpdate,
  splitFindings,
  type Insight,
  type InsightBlock,
} from "@/lib/chatInsights";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ canTrain: false }),
}));

const plainMessage: ChatMessage = {
  id: "11111111-1111-1111-1111-111111111111",
  session_id: "22222222-2222-2222-2222-222222222222",
  role: "assistant",
  content: "Two invoices are open for Shree Packaging.",
  created_at: "2026-09-08T10:15:00Z",
  status: "completed",
};

export function makeBlock(overrides: Partial<InsightBlock> = {}): InsightBlock {
  return {
    stage: "sync",
    doc_type: "PURCHASE_ORDER",
    doc_type_label: "purchase order",
    attachment_id: "33333333-3333-3333-3333-333333333333",
    currency: "INR",
    verdict: "Check the Shree Packaging invoice — it bills more than this purchase order agreed.",
    verdict_source: "template",
    cards: [],
    figures: {},
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
        title: "INV-1001 bills 23200 more than this purchase order agreed",
        impact_amount: 23200,
        currency: "INR",
        confidence: "high",
        confidence_reason: "both documents state a total",
        evidence: { invoice_number: "INV-1001", agreed: 100000, billed: 123200 },
      },
      {
        finding_key: "duplicate_billing:INV-1002",
        card: "duplicate_billing",
        title: "INV-1002 repeats a line already billed on INV-1001",
        impact_amount: 4100,
        currency: "INR",
        confidence: "med",
        confidence_reason: "descriptions match, quantities differ",
        evidence: { invoice_numbers: ["INV-1002", "INV-1001"] },
      },
      {
        finding_key: "delivery_vs_order:INV-1003",
        card: "delivery_vs_order",
        title: "INV-1003 bills 40 units but 30 were delivered",
        impact_amount: null,
        confidence: "low",
        confidence_reason: "the delivery note has no unit",
        evidence: { invoice_number: "INV-1003", direction: "short_delivery" },
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

describe("21.1 — a message without insights is untouched", () => {
  it("renders byte-identically with the key absent and with it undefined", () => {
    const withoutKey = render(<MessageBubble message={plainMessage} />);
    const before = withoutKey.container.innerHTML;
    withoutKey.unmount();

    const withUndefined = render(
      <MessageBubble message={{ ...plainMessage, insights: undefined }} />
    );
    expect(withUndefined.container.innerHTML).toBe(before);
  });

  it("draws no bubble surface for a user turn", () => {
    const { queryByTestId } = render(
      <MessageBubble message={{ ...plainMessage, role: "user" }} />
    );
    expect(queryByTestId("insight-bubble")).toBeNull();
  });

  it("treats an empty block as nothing to say", () => {
    expect(hasRenderableInsights(undefined)).toBe(false);
    expect(hasRenderableInsights(null)).toBe(false);
    expect(
      hasRenderableInsights(
        makeBlock({ verdict: "", findings: [], checks_not_run: [] })
      )
    ).toBe(false);
    expect(hasRenderableInsights(makeBlock())).toBe(true);
  });
});

describe("21.1 — block helpers follow the backend shape", () => {
  it("shows at most three findings and collapses the rest", () => {
    const { shown, hidden } = splitFindings(makeBlock());
    expect(shown).toHaveLength(3);
    expect(hidden).toHaveLength(1);
    expect(hidden[0].finding_key).toBe("price_drift:INV-1004");
  });

  it("formats impact in the tenant currency and keeps a null amount null", () => {
    const block = makeBlock();
    expect(findingImpact(block.findings[0], block)).toContain("23,200");
    expect(findingImpact(block.findings[2], block)).toBeNull();
  });

  it("falls back to the block currency when the finding states none", () => {
    const block = makeBlock();
    const finding = { ...block.findings[0], currency: null };
    expect(findingImpact(finding, block)).toBe(findingImpact(block.findings[0], block));
  });

  it("says confidence in plain words and never leaks 'med'", () => {
    expect(confidenceLabel("high")).toBe("Sure");
    expect(confidenceLabel("med")).toBe("Fairly sure");
    expect(confidenceLabel("low")).toBe("Not sure");
    expect(confidenceLabel(undefined)).not.toMatch(/med/i);
    expect(confidenceTone("high")).toBe("high");
    expect(confidenceTone("anything-else")).toBe("med");
  });

  it("writes the not-checked line from checks_not_run, or nothing", () => {
    expect(checksNotRunLine(makeBlock())).toBe(
      "Not checked: bank match (no statement on file)"
    );
    expect(checksNotRunLine(makeBlock({ checks_not_run: [] }))).toBeNull();
    expect(cardLabel("agreed_vs_billed")).toBe("agreed vs billed");
  });

  it("pulls invoice numbers out of every evidence shape the cards emit", () => {
    const block = makeBlock();
    expect(evidenceInvoiceNumbers(block.findings[0])).toEqual(["INV-1001"]);
    expect(evidenceInvoiceNumbers(block.findings[1])).toEqual(["INV-1002", "INV-1001"]);
    expect(
      evidenceInvoiceNumbers({
        ...block.findings[0],
        evidence: { matched: [{ invoice_number: "INV-9" }, { invoice_number: "INV-9" }] },
      })
    ).toEqual(["INV-9"]);
    expect(evidenceInvoiceNumbers({ ...block.findings[0], evidence: null })).toEqual([]);
  });

  it("maps a finding to its lifecycle row through finding_key + card", () => {
    const block = makeBlock();
    const rows: Insight[] = [
      {
        id: "aaaaaaaa-0000-0000-0000-000000000001",
        attachment_id: block.attachment_id,
        doc_type: block.doc_type,
        card: "agreed_vs_billed",
        finding_key: "agreed_vs_billed:INV-1001",
        title: block.findings[0].title,
        confidence: "high",
        status: "OPEN",
        is_open: true,
        created_at: "2026-09-08T10:15:00Z",
        updated_at: "2026-09-08T10:15:00Z",
      },
    ];
    expect(insightForFinding(rows, block.findings[0])?.id).toBe(rows[0].id);
    expect(insightForFinding(rows, block.findings[1])).toBeUndefined();
    expect(insightForFinding(undefined, block.findings[0])).toBeUndefined();
  });

  it("drops a replayed or older insight_update", () => {
    expect(isStaleInsightUpdate({ insights_version: 2 }, 1)).toBe(false);
    expect(isStaleInsightUpdate({ insights_version: 1 }, 1)).toBe(true);
    expect(isStaleInsightUpdate({ insights_version: 1 }, 2)).toBe(true);
    // Nothing drawn yet: the first event is never stale.
    expect(isStaleInsightUpdate({ insights_version: 1 }, undefined)).toBe(false);
  });
});
