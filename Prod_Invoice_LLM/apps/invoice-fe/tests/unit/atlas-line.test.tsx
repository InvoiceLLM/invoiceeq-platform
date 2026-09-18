// =============================================================================
// FILE: tests/unit/atlas-line.test.tsx
// FEATURE: FE Feature 23 task 2 (spec §2) — the line, and what it may not do.
//
// The assertions here are about the four parts, the doubt, the before/after
// pair, and the one boundary this feature cannot get wrong: **every number on
// screen came over the wire**. The last test is the strong form of that — it
// pulls every money-shaped token out of the rendered DOM and requires each one
// to be a string the payload actually contained.
// =============================================================================

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import AtlasLine from "@/components/atlas/AtlasLine";
import type { AtlasRecommendation } from "@/lib/atlas";
import {
  auditLine,
  loaderLine,
  trainerCorrectionLine,
  uncertainDoubtLine,
} from "./atlas-fixtures";

function renderLine(line: AtlasRecommendation, onAttach?: (l: AtlasRecommendation) => void) {
  return render(
    <ul>
      <AtlasLine line={line} onAttach={onAttach} />
    </ul>
  );
}

describe("the line renders four things, as sent", () => {
  it("prints what, why, action and verify", () => {
    renderLine(auditLine);

    expect(screen.getByTestId("atlas-line-what")).toHaveTextContent(
      auditLine.what.headline
    );
    expect(screen.getByTestId("atlas-line-why")).toHaveTextContent(auditLine.why.text);
    expect(screen.getByTestId("atlas-line-action")).toHaveTextContent(
      auditLine.action.label
    );
    expect(screen.getByTestId("atlas-line-verify")).toHaveTextContent(
      auditLine.verify.question
    );
  });

  it("opens chat on this line with the question pre-seeded and the document named", () => {
    renderLine(auditLine);

    const href = screen.getByTestId("atlas-line-verify").getAttribute("href") ?? "";
    const query = new URLSearchParams(href.split("?")[1]);
    expect(query.get("seed")).toBe(auditLine.verify.question);
    expect(query.get("verify_document_id")).toBe(auditLine.verify.document_id);
  });

  it("says out loud that it cannot yet perform an action no endpoint serves", () => {
    // BE §15.2: `routers/atlas.py` reads and writes nothing, so every action
    // kind is Slice C. A button that 404s is worse than a button that says so.
    renderLine(auditLine);
    expect(screen.getByTestId("atlas-line-action")).toBeDisabled();
    expect(screen.getByTestId("atlas-line-not-performable")).toBeInTheDocument();
  });
});

describe("uncertainty, and the correction pair", () => {
  it("renders the doubt in the server's words and never as a number or a bar", () => {
    renderLine(uncertainDoubtLine);

    const doubt = screen.getByTestId("atlas-line-doubt");
    expect(doubt).toHaveTextContent(uncertainDoubtLine.why.doubt as string);
    expect(doubt.querySelector("progress")).toBeNull();
    expect(doubt.textContent ?? "").not.toMatch(/\d+\s*%/);
  });

  it("renders the Trainer's before and after as the typed pair (D45)", () => {
    renderLine(trainerCorrectionLine);

    expect(screen.getByTestId("atlas-correction-before")).toHaveTextContent("50,000.00");
    expect(screen.getByTestId("atlas-correction-after")).toHaveTextContent("52,000.00");
  });

  it("says 'not extracted' rather than an invented before", () => {
    renderLine({
      ...trainerCorrectionLine,
      correction: { ...trainerCorrectionLine.correction!, before_rendered: null },
    });

    expect(screen.getByTestId("atlas-correction-before")).toHaveTextContent(
      "not extracted"
    );
  });
});

describe("a line missing a part is a defect, not a layout case", () => {
  it.each([
    ["why.text", { ...auditLine, why: { ...auditLine.why, text: "" } }],
    ["verify.question", { ...auditLine, verify: { question: "" } }],
    ["action.label", { ...auditLine, action: { ...auditLine.action, label: "" } }],
  ])("refuses to render a line missing %s", (_part, broken) => {
    renderLine(broken as AtlasRecommendation);

    expect(screen.getByTestId("atlas-line-defect")).toBeInTheDocument();
    expect(screen.queryByTestId("atlas-line")).toBeNull();
    // And it does not render half of it either: the headline is not shown.
    expect(screen.queryByText(auditLine.what.headline)).toBeNull();
  });

  it("refuses an uncertain line that states no doubt (BE §5.1)", () => {
    renderLine({ ...uncertainDoubtLine, why: { ...uncertainDoubtLine.why, doubt: null } });
    expect(screen.getByTestId("atlas-line-defect")).toBeInTheDocument();
  });
});

describe("no number appears that the server did not send", () => {
  /** Money-shaped, per BE §12.4: grouped, decimalised, or four digits or more. */
  const MONEY_SHAPED = /\d[\d,'  ]*\.\d+|\d{1,3}(?:,\d{2,3})+|\d{4,}/g;

  it.each([
    ["an audit line", auditLine],
    ["a doubt line", uncertainDoubtLine],
    ["a correction line", trainerCorrectionLine],
    ["a loader line", loaderLine],
  ])("prints only the payload's own figures on %s", (_name, line) => {
    const { container } = renderLine(line);

    const sent = [
      line.what.headline,
      line.why.text,
      line.why.doubt ?? "",
      line.action.label,
      line.verify.question,
      line.correction?.before_rendered ?? "",
      line.correction?.after_rendered ?? "",
      ...line.why.figures.map((figure) => figure.rendered),
      ...line.why.references,
    ].join(" ");
    const sentTokens = new Set(sent.match(MONEY_SHAPED) ?? []);

    // Token-extracted per TEXT NODE, not over `container.textContent`: two
    // adjacent spans concatenate there ("50,000.00" beside "52,000.00" reads as
    // "50,000.0052,000.00"), which would fail on a join the user never sees.
    // What a user reads is one text node at a time.
    const shown: string[] = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      shown.push(...(walker.currentNode.textContent?.match(MONEY_SHAPED) ?? []));
    }

    for (const token of shown) {
      expect(sentTokens, `the screen shows ${token}, which the payload never sent`)
        .toContain(token);
    }
  });

  it("renders one currency per line, which is the only one on the wire", () => {
    const { container } = renderLine(uncertainDoubtLine);
    const currencies = new Set(uncertainDoubtLine.why.figures.map((f) => f.currency));
    expect(currencies.size).toBe(1);
    expect(container.textContent).toContain(uncertainDoubtLine.currency);
  });
});
