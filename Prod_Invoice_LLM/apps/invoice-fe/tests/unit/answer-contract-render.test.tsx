/**
 * FE Gap 470 — `abstention` and `provenance` render on their presence, and a turn
 * without them renders no new node. FE Gap 472 — the bubble's actions use the
 * `insight_id` carried on the finding, not a joined lifecycle row.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import AbstentionCard from "@/components/chat/AbstentionCard";
import ProvenanceLine from "@/components/chat/ProvenanceLine";
import type { ChatAbstention, ChatProvenanceEntry } from "@/types/chat";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const abstention: ChatAbstention = {
  status: "insufficient_evidence",
  missing: ["a delivery note for PO-1041"],
  on_file: ["PO-1041", "RAJ-2009"],
  next_step: "Attach the delivery note and ask again",
  message: "I can't confirm the delivered quantity.",
};

describe("AbstentionCard (FE Gap 470)", () => {
  it("shows what is missing, what is on file, and a next step that SEEDS the composer", () => {
    const onSeed = vi.fn();
    const { getByTestId } = render(<AbstentionCard abstention={abstention} onSeed={onSeed} />);
    expect(getByTestId("chat-abstention").getAttribute("data-status")).toBe("insufficient_evidence");
    expect(getByTestId("chat-abstention-missing").textContent).toContain("a delivery note for PO-1041");
    expect(getByTestId("chat-abstention-on-file").textContent).toContain("RAJ-2009");
    fireEvent.click(getByTestId("chat-abstention-next-step"));
    expect(onSeed).toHaveBeenCalledWith("Attach the delivery note and ask again");
  });

  it("degrades to a disabled chip when no composer handler is supplied", () => {
    const { getByTestId } = render(<AbstentionCard abstention={abstention} />);
    expect((getByTestId("chat-abstention-next-step") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("ProvenanceLine (FE Gap 470)", () => {
  it("renders one pill per claim, linking those that name an invoice", () => {
    const entries: ChatProvenanceEntry[] = [
      { claim: "grand total", invoice_id: "11111111-2222-3333-4444-555555555555", invoice_number: "RAJ-2009", column: "grand_total" },
      { claim: "due", column: "due_date" },
    ];
    const { getAllByTestId, container } = render(<ProvenanceLine entries={entries} />);
    const pills = getAllByTestId("chat-provenance-pill");
    expect(pills).toHaveLength(2);
    expect(pills[0].textContent).toBe("RAJ-2009 · grand_total");
    expect(container.querySelector("a")?.getAttribute("href")).toBe("/audit/11111111-2222-3333-4444-555555555555");
  });

  it("renders nothing for an empty or unusable list", () => {
    const { container } = render(<ProvenanceLine entries={[{}]} />);
    expect(container.firstChild).toBeNull();
  });
});
