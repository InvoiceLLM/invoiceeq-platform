/**
 * FE Feature 22 Task 22.11 — checks disclosure on the insight bubble.
 *
 * Spec §6: "a card with 3 passed / 1 not-checked renders both counts and the
 * not-checked subjects on expand". The counts are the BACKEND's sentence
 * (`CheckLog.title()`), rendered verbatim — so the fixture's title deliberately
 * disagrees with its subject list, and a component that counted for itself
 * would fail. NOT_CHECKED is never styled as a failure.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import ChecksDisclosure from "@/components/chat/cards/ChecksDisclosure";
import { checkSummaries, type InsightBlock } from "@/lib/chatInsights";

function block(cards: InsightBlock["cards"]): InsightBlock {
  return {
    stage: "sync",
    doc_type: "PURCHASE_ORDER",
    attachment_id: "att-1",
    cards,
    findings: [],
    checks_not_run: [],
    actions: [],
    verdict: "Checked against 4 invoices.",
  };
}

const THREE_AND_ONE = block([
  {
    card: "agreed_vs_billed",
    status: "ok",
    title: "3 invoices checked, 1 not checked",
    evidence: { not_checked: [{ reason: "no matching PO line", subjects: ["RAJ-2009"], count: 1 }] },
  },
  { card: "bank_match", status: "skipped", title: "Bank match", reason: "no statement on file" },
  { card: "duplicates", status: "ok", title: "5 invoices checked", evidence: {} },
]);

describe("checkSummaries (22.11)", () => {
  it("keeps the backend's sentence for each card that ran, with its unchecked subjects by reason", () => {
    expect(checkSummaries(THREE_AND_ONE)).toEqual([
      { card: "agreed_vs_billed", title: "3 invoices checked, 1 not checked", notChecked: [{ reason: "no matching PO line", subjects: ["RAJ-2009"] }] },
      { card: "duplicates", title: "5 invoices checked", notChecked: [] },
    ]);
  });

  it("returns nothing when no card ran with a title", () => {
    expect(checkSummaries(block([{ card: "x", status: "skipped" }]))).toEqual([]);
  });
});

describe("ChecksDisclosure (22.11)", () => {
  it("renders both counts as the backend wrote them, and the not-checked subjects on expand", () => {
    render(<ChecksDisclosure summaries={checkSummaries(THREE_AND_ONE)} />);
    expect(screen.getByTestId("insight-checks-summary")).toHaveTextContent(
      "3 invoices checked, 1 not checked · 5 invoices checked"
    );
    expect(screen.queryByTestId("insight-checks-unchecked")).toBeNull();

    fireEvent.click(screen.getByRole("button"));
    const unchecked = screen.getByTestId("insight-checks-unchecked");
    expect(unchecked).toHaveTextContent("Not checked — no matching PO line: RAJ-2009");
    expect(unchecked.innerHTML).not.toMatch(/rose|red-/);
  });

  it("does not recount: the title is shown even when it disagrees with the subject list", () => {
    const summaries = checkSummaries(
      block([
        {
          card: "agreed_vs_billed",
          status: "ok",
          title: "7 invoices checked, 2 not checked",
          evidence: { not_checked: [{ reason: "no PO", subjects: ["A-1"] }] },
        },
      ])
    );
    render(<ChecksDisclosure summaries={summaries} />);
    expect(screen.getByTestId("insight-checks-summary")).toHaveTextContent("7 invoices checked, 2 not checked");
  });

  it("offers no expand when everything was checked, and renders nothing with no summaries", () => {
    const { rerender } = render(<ChecksDisclosure summaries={[{ card: "d", title: "5 invoices checked", notChecked: [] }]} />);
    expect(screen.getByRole("button")).toBeDisabled();
    rerender(<ChecksDisclosure summaries={[]} />);
    expect(screen.queryByTestId("insight-checks")).toBeNull();
  });
});
