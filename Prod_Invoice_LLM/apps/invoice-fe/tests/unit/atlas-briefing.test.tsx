// =============================================================================
// FILE: tests/unit/atlas-briefing.test.tsx
// FEATURE: FE Feature 24 (the briefing) §6 — tasks 24.1 and 24.3 to 24.6.
//
// **THE FIXTURE IS WIRE TEXT, NOT OBJECTS.** Every frame below is written in BE
// Feature 35 §3.3's shape (`event: <type>`, `data: <json>`, a blank line), split
// by `parseBriefingFrame()` and then delivered exactly as a browser's
// `EventSource` delivers it — a named event carrying the raw `data:` string. A
// fixture of pre-decoded objects would have proved the component and not the
// seam, which is the mistake the F33/F22 seam was built on.
//
// The one thing the FE decides about a briefing is whether a paragraph rests on
// a record this session can show the reader. So the fixture deliberately
// contains a paragraph with no citations and one citing an id nobody has seen,
// and the assertion is the visible count — "2 paragraphs withheld" — not the
// absence of two paragraphs. An absence proves nothing; a count is the promise.
//
// 24.2's proxy is covered in `atlas-briefing-proxy.test.ts`, which runs in the
// node environment because a Route Handler builds a `NextResponse`.
// =============================================================================

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
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

import Briefing from "@/components/atlas/Briefing";
import { BRIEFING_HIGHLIGHT_CLASS } from "@/components/atlas/BriefingParagraph";
import WorkScreen, { briefingLineLabels } from "@/components/atlas/WorkScreen";
import {
  citationLabel,
  invoiceNumberIn,
  parseBriefingFrame,
  validateCitations,
  type BriefingEvent,
} from "@/lib/atlasBriefing";
import { auditLine, linesResponse } from "./atlas-fixtures";

// ─────────────────────────────────────────────────────────────────────────────
// The scripted stream
// ─────────────────────────────────────────────────────────────────────────────

/** An `EventSource` that delivers what the test tells it to, when it says so. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  closed = false;
  onerror: ((this: EventSource, ev: Event) => any) | null = null;
  private listeners: Record<string, Array<(event: any) => void>> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (event: any) => void) {
    (this.listeners[type] ||= []).push(fn);
  }

  removeEventListener() {}

  close() {
    this.closed = true;
  }

  /** One frame, as the browser hands it over: the event name and the raw data. */
  deliver(type: string, rawData: string) {
    for (const fn of this.listeners[type] ?? []) fn({ data: rawData });
  }
}

function installEventSource() {
  FakeEventSource.instances = [];
  (window as any).EventSource = FakeEventSource;
}

/** The only open stream, or a failure that says so rather than a null deref. */
function stream(index = 0): FakeEventSource {
  const source = FakeEventSource.instances[index];
  if (!source) throw new Error(`no EventSource was opened (index ${index})`);
  return source;
}

/** Play wire text at a stream, frame by frame, inside `act()`. */
async function play(source: FakeEventSource, wire: string) {
  const frames = wire.split("\n\n").filter((f) => f.trim().length > 0);
  for (const raw of frames) {
    const type = raw
      .split("\n")
      .find((line) => line.startsWith("event:"))!
      .slice("event:".length)
      .trim();
    const data = raw
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trim())
      .join("\n");
    await act(async () => {
      source.deliver(type, data);
    });
  }
}

/** One frame of wire text. */
function frame(type: string, data: unknown): string {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

const LINE_ID = auditLine.id;
const ENTITY_ID = auditLine.what.entity_id;

const cite = (kind: string, id: string) => ({
  tool: "list_lines",
  record_kind: kind,
  record_id: id,
});

/**
 * §6's fixture: three paragraphs that stand up, one with no citations, one
 * citing a record this session has never seen — plus a `truncated`, a question
 * and the `done` footer.
 *
 * Two of the survivors cite `INVOICE-OUTSIDE-THE-LINES`, which is NOT in
 * `knownIds` and never becomes one: §7 ruling 2 allows an invoice citation from
 * outside the lines list (the backend guard proved it came from a tool) and the
 * panel renders it as a link to that invoice.
 */
const PARAGRAPHS =
  frame("paragraph", {
    text: "Two invoices are waiting on you this morning.",
    citations: [cite("recommendation", LINE_ID)],
  }) +
  frame("paragraph", {
    text: "One of them is the Kumar duplicate you saw last week.",
    citations: [cite("invoice", ENTITY_ID), cite("invoice", "INVOICE-OUTSIDE-THE-LINES")],
  }) +
  frame("paragraph", {
    text: "That same invoice is still unpaid.",
    citations: [cite("invoice", "INVOICE-OUTSIDE-THE-LINES")],
  }) +
  frame("paragraph", { text: "Cash looks fine to me.", citations: [] }) +
  frame("paragraph", {
    text: "Vendor NAT-2007 has slipped again.",
    // A `recommendation` id no line on this screen carries. The kind matters:
    // §7 ruling 2 exempts `invoice`, because the id is a destination the reader
    // can follow anyway; a recommendation id that names no line is a link to
    // nothing, which is the case this check exists for.
    citations: [cite("recommendation", "NOBODY-HAS-SEEN-THIS")],
  });

const TRUNCATED = frame("truncated", { reason: "invocations" });

const QUESTION = frame("question", {
  text: "Should I always chase this vendor at 30 days?",
  citations: [cite("recommendation", LINE_ID)],
  answer_kind: "free_text",
});

/** A second question is a backend defect; §3 step 5 says it is counted, not shown. */
const SECOND_QUESTION = frame("question", {
  text: "And should I do the same for everyone else?",
  citations: [cite("recommendation", LINE_ID)],
  answer_kind: "free_text",
});

const DONE = frame("done", { cached: false, model: "gpt-5.6-terra", dropped_paragraphs: 1 });

const SCRIPT = PARAGRAPHS + TRUNCATED + QUESTION + DONE;
const SCRIPT_TWO_QUESTIONS = PARAGRAPHS + TRUNCATED + QUESTION + SECOND_QUESTION + DONE;

const KNOWN = new Set([LINE_ID, ENTITY_ID]);

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  installEventSource();
});

afterEach(() => {
  delete (window as any).EventSource;
});

// ─────────────────────────────────────────────────────────────────────────────
// 24.1 — the parser and the one deterministic check
// ─────────────────────────────────────────────────────────────────────────────

describe("24.1 parseBriefingFrame() round-trips BE 35 §3.3", () => {
  const cases: Array<[string, unknown]> = [
    ["welcome", { role: "auditor", text: "I will watch your invoices." }],
    ["paragraph", { text: "a", citations: [cite("invoice", "x")] }],
    ["question", { text: "q", citations: [cite("rule", "r")], answer_kind: "free_text" }],
    ["truncated", { reason: "wall_clock" }],
    ["error", { message: "boom" }],
    ["done", { cached: true, model: "gpt-5.6-terra", dropped_paragraphs: 2 }],
  ];

  it.each(cases)("decodes an %s frame to its payload", (type, data) => {
    const event = parseBriefingFrame(frame(type, data)) as BriefingEvent;
    expect(event.type).toBe(type);
    expect(event.data).toEqual(data);
  });

  it("returns null for an event name outside the closed set", () => {
    expect(parseBriefingFrame(frame("thinking", { text: "…" }))).toBeNull();
  });

  it("returns null rather than throwing on data that is not JSON", () => {
    expect(parseBriefingFrame("event: paragraph\ndata: not json\n\n")).toBeNull();
  });
});

describe("24.1 validateCitations() — the only judgement the FE makes", () => {
  it("rejects a paragraph with no citations", () => {
    expect(validateCitations({ citations: [] }, KNOWN)).toEqual({
      ok: false,
      reason: "uncited",
    });
  });

  it("rejects a record id nobody has seen", () => {
    const check = validateCitations({ citations: [cite("recommendation", "nope")] }, KNOWN);
    expect(check).toEqual({ ok: false, reason: "unknown_record", recordId: "nope" });
  });

  it("allows an invoice from outside the lines list (§7 ruling 2)", () => {
    expect(validateCitations({ citations: [cite("invoice", "not-a-line")] }, KNOWN).ok).toBe(
      true
    );
  });

  it("still rejects one bad citation among good ones", () => {
    const check = validateCitations(
      { citations: [cite("recommendation", LINE_ID), cite("rule", "unseen-rule")] },
      KNOWN
    );
    expect(check.ok).toBe(false);
  });

  it("rejects an empty record id", () => {
    expect(validateCitations({ citations: [cite("orientation", "")] }, KNOWN).ok).toBe(false);
  });

  it("accepts ids from the lines payload", () => {
    expect(validateCitations({ citations: [cite("recommendation", LINE_ID)] }, KNOWN).ok).toBe(
      true
    );
  });

  it("accepts an id the briefing itself cited earlier", () => {
    // What `Briefing` does between frames: an accepted paragraph's ids widen the
    // set the next paragraph is checked against (spec §3 step 4).
    const widened = new Set([...Array.from(KNOWN), "area-audit"]);
    expect(validateCitations({ citations: [cite("action", "area-audit")] }, widened).ok).toBe(
      true
    );
    expect(validateCitations({ citations: [cite("action", "area-audit")] }, KNOWN).ok).toBe(
      false
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 24.3 — the panel
// ─────────────────────────────────────────────────────────────────────────────

describe("24.3 the panel renders what stands up and counts what does not", () => {
  it("renders 3 paragraphs and says 2 were withheld", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT);

    expect(screen.getAllByTestId("briefing-paragraph")).toHaveLength(3);
    expect(screen.getByTestId("briefing-withheld")).toHaveTextContent("2 paragraphs withheld");
  });

  it("renders the truncated line in the backend's own reason word", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT);

    expect(screen.getByTestId("briefing-truncated")).toHaveTextContent(
      "ATLAS stopped early (invocations)."
    );
  });

  it("shows the model in the footer on a fresh run and closes the stream", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT);

    expect(screen.getByTestId("briefing-footer")).toHaveTextContent("gpt-5.6-terra");
    expect(stream().closed).toBe(true);
  });

  it("says 'from cache' instead when the briefing was replayed", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(
      stream(),
      frame("paragraph", {
        text: "Yesterday's sentence, replayed.",
        citations: [cite("recommendation", LINE_ID)],
      }) + frame("done", { cached: true, model: "gpt-5.6-terra", dropped_paragraphs: 0 })
    );

    expect(screen.getByTestId("briefing-footer")).toHaveTextContent("from cache");
  });

  it("puts an error in the body instead of the paragraphs", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(
      stream(),
      frame("error", { message: "ATLAS could not write your briefing (502)." }) +
        frame("done", { cached: false, model: "", dropped_paragraphs: 0 })
    );

    expect(screen.getByTestId("briefing-error")).toHaveTextContent("(502)");
    expect(screen.queryAllByTestId("briefing-paragraph")).toHaveLength(0);
  });

  it("renders the welcome text on a cold tenant", async () => {
    render(<Briefing knownIds={new Set<string>()} />);
    await play(
      stream(),
      frame("welcome", { role: "auditor", text: "I will watch your invoices for you." }) +
        frame("done", { cached: false, model: "", dropped_paragraphs: 0 })
    );

    expect(screen.getByTestId("briefing-welcome")).toHaveTextContent(
      "I will watch your invoices for you."
    );
    expect(screen.queryByTestId("briefing-withheld")).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 24.4 — citations
// ─────────────────────────────────────────────────────────────────────────────

describe("24.4 a citation takes the reader to the record", () => {
  it("scrolls to the line with the matching id and highlights it for two seconds", async () => {
    vi.useFakeTimers();
    try {
      const line = document.createElement("div");
      line.setAttribute("data-line-id", LINE_ID);
      const scrollIntoView = vi.fn();
      (line as any).scrollIntoView = scrollIntoView;
      document.body.appendChild(line);

      render(<Briefing knownIds={KNOWN} />);
      await play(stream(), SCRIPT);

      const citation = screen
        .getAllByTestId("briefing-citation")
        .find((el) => el.getAttribute("data-citation-id") === LINE_ID)!;
      act(() => {
        (citation as HTMLButtonElement).click();
      });

      expect(scrollIntoView).toHaveBeenCalled();
      expect(line.classList.contains(BRIEFING_HIGHLIGHT_CLASS)).toBe(true);

      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(line.classList.contains(BRIEFING_HIGHLIGHT_CLASS)).toBe(false);

      line.remove();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders an invoice citation as a link to the invoice, cited or not in the lines", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT);

    const link = screen
      .getAllByTestId("briefing-citation")
      .find((el) => el.getAttribute("data-citation-id") === "INVOICE-OUTSIDE-THE-LINES")!;
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/invoices/review/INVOICE-OUTSIDE-THE-LINES");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 24.5 — the one question
// ─────────────────────────────────────────────────────────────────────────────

describe("24.5 the question is answered once and becomes a rule", () => {
  it("posts the answer with its question and shows the stored rule", async () => {
    post.mockResolvedValue({
      data: {
        id: "rule-1",
        text: "Should I always chase this vendor at 30 days? — Yes, at 30 days.",
        source: "interview",
        active: true,
        created_by: "u1",
        created_at: "2026-09-20T00:00:00Z",
        updated_at: "2026-09-20T00:00:00Z",
      },
    });

    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT);

    await userEvent.type(screen.getByTestId("briefing-question-answer"), "Yes, at 30 days.");
    await userEvent.click(screen.getByTestId("briefing-question-submit"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/atlas/briefing/answer", {
      question_text: "Should I always chase this vendor at 30 days?",
      answer: "Yes, at 30 days.",
    });
    expect(await screen.findByTestId("briefing-question-stored")).toHaveTextContent(
      "Yes, at 30 days."
    );
    expect(screen.getByTestId("briefing-question-refresh")).toHaveTextContent(
      "refresh on your next visit"
    );
  });

  it("renders only one question however many the backend sends", async () => {
    render(<Briefing knownIds={KNOWN} />);
    await play(stream(), SCRIPT_TWO_QUESTIONS);

    expect(screen.getAllByTestId("briefing-question")).toHaveLength(1);
    expect(screen.getByTestId("briefing-question")).toHaveTextContent(
      "Should I always chase this vendor at 30 days?"
    );
    // The second question frame is counted where the user can see it, with the
    // two withheld paragraphs — never silently dropped.
    expect(screen.getByTestId("briefing-withheld")).toHaveTextContent("3 paragraphs withheld");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 24.6 — the panel on the work screen
// ─────────────────────────────────────────────────────────────────────────────

function servesLines(payload: unknown) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/lines") return Promise.resolve({ data: payload });
    if (path === "/atlas/actions/kinds")
      return Promise.resolve({ data: { performable: ["resolve_invoice"], suggest_only: [] } });
    if (path === "/atlas/memory")
      return Promise.resolve({ data: { rules: [], noise_suggestions: [] } });
    if (path === "/atlas/actions") return Promise.resolve({ data: { actions: [] } });
    if (path === "/atlas/orientation") return Promise.reject(new Error("no orientation"));
    return Promise.resolve({ data: {} });
  });
}

describe("24.6 the panel sits on the work screen and never re-fetches itself", () => {
  it("asks for the lines before it asks for the briefing", async () => {
    servesLines(linesResponse([auditLine]));

    render(<WorkScreen />);

    await screen.findByTestId("briefing");
    expect(get.mock.calls.some(([path]) => path === "/atlas/lines")).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
    // The stream is opened only after the lines came back: the call log holds
    // `/atlas/lines` already, and the panel does not exist before `payload`.
    expect(stream().url).toBe("/api/atlas/briefing");
  });

  it("does not open a stream at all while the lines are still loading", () => {
    get.mockImplementation(() => new Promise(() => {}));

    render(<WorkScreen />);

    expect(screen.queryByTestId("briefing")).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("shows the refresh note after a dismiss and opens no second stream", async () => {
    servesLines(linesResponse([auditLine]));
    post.mockResolvedValue({
      data: { recommendation_id: auditLine.id, dismissed: true, created: true },
    });

    render(<WorkScreen />);
    await screen.findByTestId("briefing");
    await play(stream(), SCRIPT);

    await userEvent.click(await screen.findByTestId("atlas-line-dismiss"));

    expect(await screen.findByTestId("briefing-refresh-note")).toHaveTextContent(
      "refresh on your next visit"
    );
    expect(FakeEventSource.instances).toHaveLength(1);
    // What was already said is still on the screen: the note is a statement,
    // not a reload (D38).
    expect(screen.getAllByTestId("briefing-paragraph").length).toBeGreaterThan(0);
  });

  it("shows the refresh note after an act, and still opens no second stream", async () => {
    servesLines(linesResponse([auditLine]));
    post.mockResolvedValue({ data: { summary: "Invoice approved.", performed: true } });

    render(<WorkScreen />);
    await screen.findByTestId("briefing");
    await play(stream(), SCRIPT);

    await userEvent.click(await screen.findByTestId("atlas-line-action"));

    expect(await screen.findByTestId("briefing-refresh-note")).toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});


// ─────────────────────────────────────────────────────────────────────────────
// FE Gap 706 — a citation is labelled with the record, not its primary key
//
// The live 2026-09-20 run put `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89`
// under a paragraph about money. These assert the reader sees the invoice
// number the payload already carries, and that the id is still on the element
// for anyone checking.
// ─────────────────────────────────────────────────────────────────────────────

describe("FE Gap 706 citation labels come from data, never from the id", () => {
  it("reads the invoice number out of a headline, and nothing else", () => {
    expect(invoiceNumberIn("Rajesh Steel Corporation #RAJ-2009")).toBe("RAJ-2009");
    expect(invoiceNumberIn("Kumar Supplies #1041 is waiting on you")).toBe("1041");
    expect(invoiceNumberIn("VPI-OUT-2014 needs review")).toBe("VPI-OUT-2014");
    // A money figure is not an invoice number, and neither is a bare date.
    expect(invoiceNumberIn("4,37,190.00 is due on 15 September")).toBeNull();
    expect(invoiceNumberIn("Cash looks fine to me.")).toBeNull();
    expect(invoiceNumberIn("")).toBeNull();
  });

  it("labels each kind from what it has, and falls back rather than printing an id", () => {
    const labels = new Map([[LINE_ID, "RAJ-2009"]]);
    expect(citationLabel(cite("recommendation", LINE_ID), "anything", labels)).toBe("RAJ-2009");
    // No entry for this line: a word, not the id.
    expect(citationLabel(cite("recommendation", "other"), "anything", labels)).toBe("this line");
    expect(citationLabel(cite("invoice", "an-id"), "VPI-OUT-2014 does not add up.")).toBe(
      "VPI-OUT-2014"
    );
    expect(citationLabel(cite("invoice", "an-id"), "No number in this sentence.")).toBe(
      "invoice"
    );
    expect(citationLabel(cite("rule", "r-1"), "")).toBe("memory rule");
    expect(citationLabel(cite("action", "a-1"), "")).toBe("action");
    expect(citationLabel(cite("recon_row", "x"), "")).toBe("recon row");
  });

  it("builds the map WorkScreen hands the panel from the lines payload", () => {
    expect(briefingLineLabels([auditLine]).get(auditLine.id)).toBe("1041");
    expect(briefingLineLabels([]).size).toBe(0);
  });

  it("never renders a record id as the visible label, and keeps it on the element", async () => {
    servesLines(linesResponse([auditLine]));

    render(<WorkScreen />);
    await screen.findByTestId("briefing");
    await play(stream(), SCRIPT);

    const citations = screen.getAllByTestId("briefing-citation");
    expect(citations.length).toBeGreaterThan(0);
    for (const el of citations) {
      const id = el.getAttribute("data-citation-id")!;
      expect(el.textContent).not.toBe(id);
      // The id is still reachable — title and aria-label carry it verbatim.
      expect(el.getAttribute("title")).toContain(id);
      expect(el.getAttribute("aria-label")).toContain(id);
    }

    const line = citations.find((el) => el.getAttribute("data-citation-id") === LINE_ID)!;
    expect(line.textContent).toBe("1041");
  });
});
