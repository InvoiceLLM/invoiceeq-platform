// =============================================================================
// FILE: tests/unit/atlas-actions.test.tsx
// FEATURE: FE Feature 23 tasks 4 and (the FE half of) BE Feature 34 task 34.7 —
//          the work screen can finally DO something, on exactly two kinds.
//
// WHAT THESE TESTS ARE FOR, AND WHAT THEY CANNOT PROVE.
// They prove the wiring: which button is enabled, what it posts, what it does
// afterwards, and that a suggest-only line is a link rather than a write. They
// CANNOT prove that an invoice is resolved — `apiClient` is mocked here, so
// nothing reaches a database. That is a property of the backend and the
// browser, and it is proven in BE Feature 34 §17: a real click on /work, and the
// row read back out of Postgres.
//
// THE RULE THIS FILE GUARDS ABOVE ALL OTHERS: a button is never enabled ahead of
// its endpoint. `PERFORMABLE_ACTION_KINDS` is empty on this side and stays
// empty; what is performable comes from `GET /atlas/actions/kinds` at runtime.
// The first test below is the one that fails if anybody ever "fixes" that by
// hard-coding the list.
//
// FE Gap 641's lesson is applied: anything awaiting an async child waits for the
// child, never for the container.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/work",
  useSearchParams: () => new URLSearchParams(),
}));

import WorkScreen from "@/components/atlas/WorkScreen";
import { PERFORMABLE_ACTION_KINDS } from "@/lib/atlas";
import {
  auditLine,
  linesResponse,
  loaderLine,
  trainerCorrectionLine,
} from "./atlas-fixtures";

/** What BE 34.7 actually serves: D50/D51's two kinds and nothing else. */
const KINDS = {
  performable: ["resolve_invoice", "retry_ingestion_source"],
  suggest_only: ["apply_field_correction", "requeue_invoices"],
  dispositions: {
    resolve_invoice: "perform",
    retry_ingestion_source: "perform",
    apply_field_correction: "suggest",
    requeue_invoices: "suggest",
    open_field_review: "navigate",
    attach_witness_document: "instruct",
  },
};

function serves(payload: unknown, kinds: unknown = KINDS) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/lines") return Promise.resolve({ data: payload });
    if (path === "/atlas/actions/kinds") return Promise.resolve({ data: kinds });
    if (path === "/documents") return Promise.resolve({ data: [] });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

/**
 * Wait for the action button of one line to reach a performable state.
 *
 * The button and the answer that says whether it may be clicked arrive from two
 * different requests — `/atlas/lines` renders it, `/atlas/actions/kinds` enables
 * it. Waiting only for the button races the second request and finds it
 * disabled. FE Gap 641, exactly.
 */
async function enabledAction(kind: string): Promise<HTMLButtonElement> {
  const button = (await screen.findByTestId("atlas-line-action")) as HTMLButtonElement;
  await waitFor(() => expect(button.dataset.performable).toBe("yes"));
  expect(button.dataset.actionKind).toBe(kind);
  return button;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("34.7d — the performable set comes from the backend, never from here", () => {
  it("keeps its own list empty, so a button can never be enabled ahead of an endpoint", () => {
    // Slice B's honesty mechanism, still intact. If a future change transcribes
    // the backend's list into this constant, this fails — which is the point.
    expect(PERFORMABLE_ACTION_KINDS.size).toBe(0);
  });

  it("renders every action disabled until the backend has said what it can do", async () => {
    // The kinds read never resolves, which is the pre-answer state.
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines") return Promise.resolve({ data: linesResponse([auditLine]) });
      if (path === "/atlas/actions/kinds") return new Promise(() => {});
      // FE Gaps 700/701: the work screen now also carries the memory panel and
      // the action log, each of which reads on mount. Served empty here -- this
      // test is about the action button's disabled state and nothing else.
      if (path === "/atlas/memory")
        return Promise.resolve({ data: { rules: [], noise_suggestions: [] } });
      if (path === "/atlas/actions") return Promise.resolve({ data: { entries: [] } });
      return Promise.resolve({ data: [] });
    });

    render(<WorkScreen />);

    const button = (await screen.findByTestId("atlas-line-action")) as HTMLButtonElement;
    expect(button).toBeDisabled();
    expect(button.dataset.performable).toBe("no");
  });

  it("leaves every action disabled when the kinds read fails", async () => {
    // "I do not know whether I can do this" must not render as "I can".
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines") return Promise.resolve({ data: linesResponse([auditLine]) });
      if (path === "/atlas/actions/kinds") return Promise.reject(new Error("down"));
      // FE Gaps 700/701, as above: served empty, out of this test's way.
      if (path === "/atlas/memory")
        return Promise.resolve({ data: { rules: [], noise_suggestions: [] } });
      if (path === "/atlas/actions") return Promise.resolve({ data: { entries: [] } });
      return Promise.resolve({ data: [] });
    });

    render(<WorkScreen />);

    const button = (await screen.findByTestId("atlas-line-action")) as HTMLButtonElement;
    await waitFor(() => expect(button).toBeDisabled());
    expect(screen.queryByTestId("work-screen-error")).toBeNull();
  });
});

describe("34.7a — the two performable kinds post, then re-read", () => {
  it("posts the line's own kind and target, and prints the server's sentence", async () => {
    serves(linesResponse([auditLine]));
    post.mockResolvedValue({
      data: {
        recommendation_id: auditLine.id,
        kind: "resolve_invoice",
        target_id: auditLine.action.target_id,
        performed: true,
        summary: "Invoice approved.",
        detail: {},
      },
    });

    render(<WorkScreen />);
    await userEvent.click(await enabledAction("resolve_invoice"));

    expect(post).toHaveBeenCalledWith(`/atlas/lines/${encodeURIComponent(auditLine.id)}/act`, {
      kind: "resolve_invoice",
      target_id: auditLine.action.target_id,
      params: auditLine.action.params,
    });
    // The outcome is the SERVER's sentence, printed as sent.
    expect(await screen.findByTestId("work-screen-outcome")).toHaveTextContent(
      "Invoice approved."
    );
  });

  it("re-reads the lines rather than splicing the row out locally", async () => {
    serves(linesResponse([auditLine]));
    post.mockResolvedValue({ data: { performed: true, summary: "Invoice approved." } });

    render(<WorkScreen />);
    await enabledAction("resolve_invoice");
    const readsBefore = get.mock.calls.filter(([p]) => p === "/atlas/lines").length;

    await userEvent.click(screen.getByTestId("atlas-line-action"));

    // D38 recomputes on open; whether the line survives its own action is the
    // server's answer, not this component's.
    await waitFor(() =>
      expect(get.mock.calls.filter(([p]) => p === "/atlas/lines").length).toBe(
        readsBefore + 1
      )
    );
  });

  it("says a failed action out loud and changes nothing on the screen", async () => {
    serves(linesResponse([auditLine]));
    post.mockRejectedValue({
      response: { data: { detail: "You do not have permission to do this." } },
    });

    render(<WorkScreen />);
    await userEvent.click(await enabledAction("resolve_invoice"));

    expect(await screen.findByTestId("work-screen-error")).toHaveTextContent(
      "You do not have permission to do this."
    );
    expect(screen.queryByTestId("work-screen-outcome")).toBeNull();
  });

  it("enables the Loader's per-source retry, which is the other ruled kind (D51)", async () => {
    serves(linesResponse([loaderLine], { capabilities: ["load"] }));
    post.mockResolvedValue({ data: { performed: true, summary: "Ran this source." } });

    render(<WorkScreen />);
    await userEvent.click(await enabledAction("retry_ingestion_source"));

    expect(post).toHaveBeenCalledWith(
      `/atlas/lines/${encodeURIComponent(loaderLine.id)}/act`,
      expect.objectContaining({ kind: "retry_ingestion_source" })
    );
  });
});

describe("34.7e — a suggest-only kind is a destination, never a write (D50)", () => {
  it("renders a link to where the decision is made, and posts nothing", async () => {
    serves(linesResponse([trainerCorrectionLine], { capabilities: ["train"] }));

    render(<WorkScreen />);

    const link = await screen.findByTestId("atlas-line-destination");
    expect(link).toHaveAttribute(
      "href",
      `/invoices/review/${trainerCorrectionLine.action.target_id}`
    );
    expect(link.getAttribute("data-action-kind")).toBe("apply_field_correction");
    // There is no button for it at all, so there is nothing to click that could
    // become a write by somebody wiring an onClick later.
    expect(screen.queryByTestId("atlas-line-action")).toBeNull();
    await userEvent.click(link);
    expect(post).not.toHaveBeenCalled();
  });

  it("says it is the user's decision, not that the feature is unfinished", async () => {
    serves(linesResponse([trainerCorrectionLine], { capabilities: ["train"] }));

    render(<WorkScreen />);

    const note = await screen.findByTestId("atlas-line-not-performable");
    // D50 is a ruling, not a backlog item, and the wording has to reflect that.
    expect(note.textContent).toContain("yours to decide");
    expect(note.textContent).not.toContain("cannot do it for you yet");
  });
});

describe("34.7f — the ranking cut hides nothing", () => {
  const many = Array.from({ length: 5 }, (_, i) => ({
    ...auditLine,
    id: `audit-approve-${i}`,
    what: { ...auditLine.what, headline: `Line ${i}` },
  }));

  it("shows the cut, and reveals the rest from the payload it already has", async () => {
    serves(linesResponse(many, { rank_cut: 2 }));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(2));
    const readsBefore = get.mock.calls.filter(([p]) => p === "/atlas/lines").length;

    await userEvent.click(screen.getByTestId("work-screen-show-everything"));

    expect(screen.getAllByTestId("atlas-line")).toHaveLength(5);
    // D30: everything below the cut was already here. Revealing it must not
    // depend on a request that can fail.
    expect(get.mock.calls.filter(([p]) => p === "/atlas/lines").length).toBe(readsBefore);
  });

  it("offers no reveal control when everything already fits", async () => {
    serves(linesResponse(many, { rank_cut: 50 }));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(5));
    expect(screen.queryByTestId("work-screen-show-everything")).toBeNull();
  });

  it("renders the server's order and never re-sorts it", async () => {
    serves(linesResponse(many, { rank_cut: 50 }));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(5));
    const rendered = screen
      .getAllByTestId("atlas-line-what")
      .map((node) => node.textContent);
    expect(rendered).toEqual(many.map((line) => line.what.headline));
  });
});

describe("FE task 4 — collapsed rows for the Admin (BE §2.2, D20)", () => {
  const areaLines = [
    { ...trainerCorrectionLine, id: "train-1" },
    { ...trainerCorrectionLine, id: "train-2" },
  ];
  const payload = linesResponse(areaLines, {
    capabilities: ["audit", "train", "load", "admin"],
    areas: [
      {
        capability: "train" as const,
        label: "Corrections",
        count: 2,
        untouched: 1,
        age_unknown: 0,
        reason: "someone else is working this",
        headline: "Corrections — 2 pending, 1 untouched for a week.",
        line_ids: ["train-1", "train-2"],
      },
    ],
  });

  it("renders the server's headline verbatim, with its aging figure", async () => {
    serves(payload);

    render(<WorkScreen />);

    expect(await screen.findByTestId("work-screen-area-headline")).toHaveTextContent(
      "Corrections — 2 pending, 1 untouched for a week."
    );
  });

  it("opens in place, out of the payload it already holds", async () => {
    serves(payload);

    render(<WorkScreen />);

    const toggle = await screen.findByTestId("work-screen-area-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("work-screen-area-lines")).toBeNull();
    const readsBefore = get.mock.calls.filter(([p]) => p === "/atlas/lines").length;

    await userEvent.click(toggle);

    const opened = await screen.findByTestId("work-screen-area-lines");
    expect(opened.querySelectorAll("[data-testid='atlas-line']")).toHaveLength(2);
    // "Coverage is total; volume is not" — the rows were already here, so
    // expanding one cannot fail and cannot be a permission decision.
    expect(get.mock.calls.filter(([p]) => p === "/atlas/lines").length).toBe(readsBefore);
  });

  /**
   * **The defect real data found (2026-09-18), asserted the way it was found:
   * by counting what is on the screen.**
   *
   * All nine lines rendered twice — once inside their area, once in the list
   * below it. The suite had asserted that the area held two lines and that the
   * list held two lines, and both were true. Nobody counted the screen.
   */
  it("renders a line exactly once, no matter how the area is left", async () => {
    serves(payload);

    render(<WorkScreen />);

    // Collapsed: the two lines belong to the area, so neither is loose.
    await screen.findByTestId("work-screen-area-headline");
    expect(screen.queryAllByTestId("atlas-line")).toHaveLength(0);
    expect(screen.queryByTestId("work-screen-lines")).toBeNull();

    // Opened: each line appears once, inside the area it belongs to.
    await userEvent.click(screen.getByTestId("work-screen-area-toggle"));
    expect(await screen.findByTestId("work-screen-area-lines")).toBeTruthy();
    expect(screen.getAllByTestId("atlas-line")).toHaveLength(2);
    for (const id of ["train-1", "train-2"]) {
      expect(
        screen.getAllByTestId("atlas-line").filter((n) => n.getAttribute("data-line-id") === id)
      ).toHaveLength(1);
    }
  });

  it("leaves a line no area stands for in the plain list, once", async () => {
    /** The cash tile: `audit` capability, not decision work, in no area. */
    const tile = { ...auditLine, id: "audit-cash-INR" };
    serves(
      linesResponse([...areaLines, tile], {
        capabilities: ["audit", "train", "load", "admin"],
        areas: payload.areas,
      })
    );

    render(<WorkScreen />);

    await screen.findByTestId("work-screen-area-headline");
    const loose = screen.getAllByTestId("atlas-line");
    expect(loose).toHaveLength(1);
    expect(loose[0].getAttribute("data-line-id")).toBe("audit-cash-INR");
  });

  it("renders no area rows at all when the server sends none", async () => {
    serves(linesResponse(areaLines));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("work-screen-areas")).toBeNull();
  });
});

// =============================================================================
// FE task 9 (spec §5) and the "you missed this" affordance — BE tasks 34.12 and
// 34.14. Both are content the SERVER owns; these tests assert this app renders
// it and composes none of it.
// =============================================================================

import ColdStart from "@/components/atlas/ColdStart";
import MissedThis from "@/components/atlas/MissedThis";

const ORIENTATION = {
  needed: true,
  capabilities: ["audit"],
  parts: [
    { key: "your_job", title: "What your job looks like with me", body: "You approve or reject." },
    { key: "how_to_verify", title: "How to check me", body: "Attach the document and ask me." },
    {
      key: "what_i_will_learn",
      title: "What I will be able to do as I learn",
      body: "Right now I do not know your vendors. In a month I will.",
    },
  ],
  day_one_finds: ["an invoice whose line items do not add up"],
  historical_import_offer: "It is an offer, not a step.",
};

describe("FE task 9 — cold start (BE §7.1, D24/D25)", () => {
  it("renders all three parts, including the one that says what ATLAS cannot do yet", async () => {
    get.mockImplementation((path: string) =>
      path === "/atlas/orientation"
        ? Promise.resolve({ data: ORIENTATION })
        : Promise.reject(new Error(`unexpected GET ${path}`))
    );

    render(<ColdStart />);

    const parts = await screen.findAllByTestId("atlas-cold-start-part");
    expect(parts).toHaveLength(3);
    // Part 3 is the commitment, and it is the one most likely to be dropped.
    expect(
      screen.getByTestId("atlas-cold-start-parts").textContent
    ).toContain("In a month I will.");
  });

  it("says what it can already catch, so day one does not read as nothing", async () => {
    get.mockResolvedValue({ data: ORIENTATION });

    render(<ColdStart />);

    expect(await screen.findByTestId("atlas-cold-start-day-one")).toHaveTextContent(
      "do not add up"
    );
    // The historical import is a sentence, never a required step (§7.1).
    expect(screen.getByTestId("atlas-cold-start-import-offer")).toHaveTextContent(
      "offer, not a step"
    );
  });

  it("renders nothing once the workspace has history (D25)", async () => {
    get.mockResolvedValue({ data: { ...ORIENTATION, needed: false } });

    const { container } = render(<ColdStart />);

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByTestId("atlas-cold-start")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("stays silent when the read fails, rather than putting an error over the work", async () => {
    get.mockRejectedValue(new Error("down"));

    render(<ColdStart />);

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByTestId("atlas-cold-start")).toBeNull();
  });
});

describe("34.14 — 'you missed this' (D34)", () => {
  it("sends the user's sentence exactly as typed", async () => {
    post.mockResolvedValue({ data: { id: "r1", rule: { id: "m1", text: "…" } } });

    render(<MissedThis entityKind="invoice" entityId="inv-1" />);

    await userEvent.click(screen.getByTestId("atlas-missed-open"));
    const typed = "you did not flag Kumar billing twice  ";
    await userEvent.type(screen.getByTestId("atlas-missed-text"), typed);
    await userEvent.click(screen.getByTestId("atlas-missed-send"));

    await waitFor(() => expect(post).toHaveBeenCalled());
    // Unedited. It is the evidence ATLAS was wrong, not a form field to tidy.
    expect(post).toHaveBeenCalledWith("/atlas/missed", {
      entity_kind: "invoice",
      entity_id: "inv-1",
      description: typed,
    });
  });

  it("acknowledges plainly and stops, and says where the lesson went", async () => {
    post.mockResolvedValue({ data: { id: "r1", rule: { id: "m1", text: "…" } } });

    render(<MissedThis entityKind="invoice" entityId="inv-1" />);
    await userEvent.click(screen.getByTestId("atlas-missed-open"));
    await userEvent.type(screen.getByTestId("atlas-missed-text"), "missed a duplicate");
    await userEvent.click(screen.getByTestId("atlas-missed-send"));

    const done = await screen.findByTestId("atlas-missed-done");
    expect(done).toHaveTextContent("in your words");
    expect(screen.queryByTestId("atlas-missed-text")).toBeNull();
  });

  it("cannot be sent empty, so a blank report never becomes a blank lesson", async () => {
    render(<MissedThis entityKind="invoice" entityId="inv-1" />);
    await userEvent.click(screen.getByTestId("atlas-missed-open"));
    expect(screen.getByTestId("atlas-missed-send")).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("says a failed report out loud rather than claiming it was recorded", async () => {
    post.mockRejectedValue({ response: { data: { detail: "tell me what I missed" } } });

    render(<MissedThis entityKind="invoice" entityId="inv-1" />);
    await userEvent.click(screen.getByTestId("atlas-missed-open"));
    await userEvent.type(screen.getByTestId("atlas-missed-text"), "x");
    await userEvent.click(screen.getByTestId("atlas-missed-send"));

    expect(await screen.findByTestId("atlas-missed-error")).toHaveTextContent(
      "tell me what I missed"
    );
    expect(screen.queryByTestId("atlas-missed-done")).toBeNull();
  });
});
