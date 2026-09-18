// =============================================================================
// FILE: tests/unit/atlas-work-screen.test.tsx
// FEATURE: FE Feature 23 task 3 (spec §3) and task 6 (spec §6).
//
// The two things this screen must not get wrong:
//   1. "No tasks assigned" is the SERVER's statement (`ungranted`), never an
//      inference from an empty list (D3). An Auditor who is simply clear this
//      morning must not be told they have no access.
//   2. A line the caller cannot act on is ABSENT. The FE filters nothing, so
//      the test asserts what is in the payload is what is on the screen —
//      including the negative: a payload of `load` lines renders no `audit`
//      line, because the server sent none.
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

import WorkScreen, { NO_TASKS_ASSIGNED } from "@/components/atlas/WorkScreen";
import { auditLine, linesResponse, loaderLine, uncertainDoubtLine } from "./atlas-fixtures";

function servesLines(payload: unknown) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/lines") return Promise.resolve({ data: payload });
    if (path === "/documents") return Promise.resolve({ data: [] });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

/**
 * Pick a statement from the recon document picker.
 *
 * The `<select>` and its `<option>`s arrive from two different requests:
 * `/atlas/lines` renders the panel, `/documents` fills it. Waiting only for the
 * select — which is what these tests did — races the second request, and the
 * select is then present with nothing in it but the placeholder. It passed when
 * the file ran alone and failed under the full suite, where the extra scheduling
 * pressure let the render win. FE Gap 641.
 */
async function pickDocument(id: string) {
  const picker = (await screen.findByTestId("atlas-recon-document")) as HTMLSelectElement;
  await waitFor(() =>
    expect(Array.from(picker.options).some((o) => o.value === id)).toBe(true)
  );
  await userEvent.selectOptions(picker, id);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("the no-grants empty state (D3)", () => {
  it("renders the stated position and zero lines", async () => {
    servesLines(
      linesResponse([], { ungranted: true, capabilities: [], doubt_checks_run: 0 })
    );

    render(<WorkScreen />);

    expect(await screen.findByTestId("work-screen-ungranted")).toHaveTextContent(
      NO_TASKS_ASSIGNED
    );
    expect(screen.queryAllByTestId("atlas-line")).toHaveLength(0);
    expect(screen.queryByTestId("work-screen-lines")).toBeNull();
  });

  it("says something different when the caller has grants and no work", async () => {
    servesLines(linesResponse([], { doubt_checks_run: 0 }));

    render(<WorkScreen />);

    expect(await screen.findByTestId("work-screen-clear")).toBeInTheDocument();
    expect(screen.queryByTestId("work-screen-ungranted")).toBeNull();
  });
});

describe("capability-filtered rendering — the FE filters nothing", () => {
  it("renders exactly the lines the server sent, in the order it sent them", async () => {
    servesLines(linesResponse([auditLine, uncertainDoubtLine]));

    render(<WorkScreen />);

    await waitFor(() =>
      expect(screen.getAllByTestId("atlas-line")).toHaveLength(2)
    );
    expect(
      screen.getAllByTestId("atlas-line").map((el) => el.getAttribute("data-line-id"))
    ).toEqual([auditLine.id, uncertainDoubtLine.id]);
  });

  it("shows no audit line to a caller the server sent only load lines", async () => {
    servesLines(linesResponse([loaderLine], { capabilities: ["load"] }));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(1));
    const capabilities = screen
      .getAllByTestId("atlas-line")
      .map((el) => el.getAttribute("data-capability"));
    expect(capabilities).toEqual(["load"]);
    // Absent, not disabled (BE §2.1): there is no hidden or greyed audit row.
    expect(screen.queryByText(auditLine.what.headline)).toBeNull();
  });

  it("does not hide a failed read behind an empty screen", async () => {
    get.mockRejectedValue({ response: { data: { detail: "Backend unavailable" } } });

    render(<WorkScreen />);

    expect(await screen.findByTestId("work-screen-error")).toHaveTextContent(
      "Backend unavailable"
    );
    expect(screen.queryByTestId("work-screen-clear")).toBeNull();
  });
});

describe("recon attach and the four groups (§6)", () => {
  const reconResponse = {
    vendor_name: "Kumar Supplies",
    currency: "INR",
    document_id: "doc-1",
    agrees: false,
    unreadable_rows: 1,
    groups: {
      matched: [{ invoice_number: "INV-1041", invoice_id: "inv-1", amount_rendered: "50,000.00" }],
      they_show_we_do_not: [{ invoice_number: "INV-9999", amount_rendered: "12,000.00" }],
      we_show_they_do_not: [{ invoice_number: "1043", invoice_id: "inv-3", amount_rendered: "25,000.00" }],
      amount_differs: [
        {
          invoice_number: "INV-1042",
          invoice_id: "inv-2",
          amount_rendered: "1,00,000.00",
          theirs_rendered: "98,000.00",
          ours_rendered: "1,00,000.00",
          difference_rendered: "-2,000.00",
        },
      ],
      unmatchable: [{ invoice_number: null, amount_rendered: "4,000.00" }],
    },
    lines: [],
  };

  it("offers the attach affordance only on a line whose action asks for it", async () => {
    servesLines(linesResponse([auditLine]));

    render(<WorkScreen />);

    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(1));
    // The audit line's action is `resolve_invoice`, so no attach control and no
    // recon panel: the FE never decides a document is needed (§6).
    expect(screen.queryByTestId("atlas-line-attach")).toBeNull();
    expect(screen.queryByTestId("atlas-recon")).toBeNull();
  });

  it("renders the four groups from the server's own rows", async () => {
    servesLines(linesResponse([uncertainDoubtLine]));
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines")
        return Promise.resolve({ data: linesResponse([uncertainDoubtLine]) });
      if (path === "/documents")
        return Promise.resolve({
          data: [{ id: "doc-1", counterparty_name: "Kumar Supplies", file_path: "statement.pdf" }],
        });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    post.mockResolvedValue({ data: reconResponse });

    render(<WorkScreen />);

    // The panel is offered because the SERVER sent a line asking for a document.
    expect(await screen.findByTestId("atlas-recon")).toBeInTheDocument();
    await pickDocument("doc-1");
    await userEvent.click(screen.getByTestId("atlas-recon-compare"));

    await waitFor(() => expect(screen.getByTestId("atlas-recon-result")).toBeInTheDocument());
    for (const group of [
      "matched",
      "they_show_we_do_not",
      "we_show_they_do_not",
      "amount_differs",
      "unmatchable",
    ]) {
      expect(screen.getByTestId(`recon-group-${group}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("recon-theirs")).toHaveTextContent("98,000.00");
    expect(screen.getByTestId("recon-ours")).toHaveTextContent("1,00,000.00");
    // The difference is the SERVER's subtraction, printed. Nothing here computed it.
    expect(screen.getByTestId("recon-difference")).toHaveTextContent("-2,000.00");
    expect(screen.getByTestId("atlas-recon-unreadable")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/atlas/recon", { document_id: "doc-1" });
  });

  it("shows the backend's own refusal rather than a generic failure", async () => {
    servesLines(linesResponse([uncertainDoubtLine]));
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines")
        return Promise.resolve({ data: linesResponse([uncertainDoubtLine]) });
      // FE Gaps 700/701: the memory panel and the action log read on mount and
      // are not what this test is about. Named explicitly rather than left to
      // the document fall-through below, which would hand each of them a list.
      if (path === "/atlas/memory")
        return Promise.resolve({ data: { rules: [], noise_suggestions: [] } });
      if (path === "/atlas/actions") return Promise.resolve({ data: { entries: [] } });
      return Promise.resolve({ data: [{ id: "doc-1", file_path: "s.pdf" }] });
    });
    post.mockRejectedValue({
      response: { data: { detail: "Tell me whose statement it is." } },
    });

    render(<WorkScreen />);
    await pickDocument("doc-1");
    await userEvent.click(screen.getByTestId("atlas-recon-compare"));

    expect(await screen.findByTestId("atlas-recon-error")).toHaveTextContent(
      "Tell me whose statement it is."
    );
  });
});

describe("what this screen deliberately does not do", () => {
  it("renders no batch control of any kind (D42)", async () => {
    servesLines(linesResponse([auditLine, uncertainDoubtLine]));

    const { container } = render(<WorkScreen />);
    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(2));

    // D42 ruled nothing batchable in v1, so §10's "an uncertain line is never
    // inside a batch control" is vacuous. This is the stronger, checkable fact:
    // there is no batch control at all to put a line inside.
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(container.textContent).not.toMatch(/approve (all|these)/i);
    expect(container.textContent).not.toMatch(/select all/i);
  });

  it("sends nothing, and polls nothing, on open (D36, D38)", async () => {
    servesLines(linesResponse([auditLine]));

    render(<WorkScreen />);
    await waitFor(() => expect(screen.getAllByTestId("atlas-line")).toHaveLength(1));

    // One read, no write. Every outbound-message action kind is Slice C, and
    // there is no UI path here that sends anything at all, let alone two things
    // on one click.
    expect(post).not.toHaveBeenCalled();
    expect(get.mock.calls.filter(([path]) => path === "/atlas/lines")).toHaveLength(1);
  });
});
