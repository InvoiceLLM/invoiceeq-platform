// =============================================================================
// FILE: tests/unit/atlas-memory.test.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.10 (§7.2, D31, D40, D12).
//          FE Gap 700.
//
// WHAT THESE TESTS PROVE, AND WHAT THEY CANNOT. They prove the wiring: which
// verb each control sends, to which path, with which body, and that every write
// is followed by a re-read rather than a local edit. They CANNOT prove a rule
// left Postgres — `apiClient` is mocked here. The hard delete is proven against
// a live backend and read back out of the database; that evidence is in
// FE Feature 23 §15 and BE Feature 34 §17, not in this file.
//
// THE D40 TEST IS THE ONE THAT MATTERS MOST HERE. A derived observation (a
// vendor's usual range) is not a memory rule and must never be listed as one:
// offering to "edit" a figure recomputed from the customer's own invoices is a
// category error. The assertion is structural rather than about copy — this
// component has exactly one source of rows, `GET /atlas/memory`'s `rules`, and
// reads nothing else at all.
//
// FE Gap 641's lesson is applied: anything awaiting an async child waits for the
// child, never for the container.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const del = vi.fn();

vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    get: (...args: any[]) => get(...args),
    post: (...args: any[]) => post(...args),
    patch: (...args: any[]) => patch(...args),
    put: vi.fn(),
    delete: (...args: any[]) => del(...args),
  },
}));

import MemoryPanel, { MEMORY_SCOPE_NOTE } from "@/components/atlas/MemoryPanel";

/** A told rule and a switched-off one — both must be listed (§7.2). */
const RULES = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    text: "Kumar Supplies always bills in INR, never USD.",
    source: "told",
    origin_ref: null,
    active: true,
    created_by: "user_test_default",
    created_at: "2026-09-18T06:00:00",
    updated_at: "2026-09-18T06:00:00",
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    text: "ATLAS missed this: the delivery note total did not match.",
    source: "missed",
    origin_ref: "invoice:8f2c3e91",
    active: false,
    created_by: "user_second",
    created_at: "2026-09-17T06:00:00",
    updated_at: "2026-09-17T09:00:00",
  },
];

const SUGGESTION = {
  family: "audit-approve",
  description: "invoices awaiting a decision",
  count: 41,
  text: "You have dismissed this 41 times. Shall I stop raising it?",
};

function serves(rules: unknown[], suggestions: unknown[] = []) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/memory")
      return Promise.resolve({ data: { rules, noise_suggestions: suggestions } });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

/** Open the panel and wait for the rows themselves, not for the container. */
async function openPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId("atlas-memory-toggle"));
  return screen.findAllByTestId("atlas-memory-rule");
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  del.mockReset();
});

describe("what ATLAS remembers is readable (§7.2, D31)", () => {
  it("lists every rule, including one that is switched off", async () => {
    serves(RULES);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    const rows = await openPanel(user);
    expect(rows).toHaveLength(2);
    // The promise is that a wrong lesson can be FOUND. A switched-off rule the
    // user cannot see is one they can neither switch back on nor delete.
    expect(rows[1].dataset.active).toBe("false");
  });

  it("shows each rule's provenance, which is what makes a wrong one judgeable", async () => {
    serves(RULES);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    const sources = await screen.findAllByTestId("atlas-memory-rule-source");
    expect(sources.map((node) => node.textContent)).toEqual(["told", "missed"]);
  });

  it("says a failed read is a failed read, rather than rendering an empty memory", async () => {
    get.mockRejectedValue({ response: { data: { detail: "backend is down" } } });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await user.click(await screen.findByTestId("atlas-memory-toggle"));
    expect(await screen.findByTestId("atlas-memory-error")).toHaveTextContent("backend is down");
    expect(screen.queryByTestId("atlas-memory-rule")).toBeNull();
  });
});

describe("a wrong lesson can be changed or removed (§7.2)", () => {
  it("edits a rule with PATCH and re-reads instead of patching local state", async () => {
    serves(RULES);
    patch.mockResolvedValue({ data: RULES[0] });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);

    await user.click((await screen.findAllByTestId("atlas-memory-rule-edit"))[0]);
    const box = await screen.findByTestId("atlas-memory-edit-text");
    await user.clear(box);
    await user.type(box, "Kumar Supplies bills in INR.");
    await user.click(await screen.findByTestId("atlas-memory-edit-save"));

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][0]).toBe(`/atlas/memory/${RULES[0].id}`);
    expect(patch.mock.calls[0][1]).toEqual({ text: "Kumar Supplies bills in INR." });
    // The re-read is the point: the list shows the server's rows afterwards.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("switching a rule off is a PATCH, not a delete — they are different acts", async () => {
    serves(RULES);
    patch.mockResolvedValue({ data: { ...RULES[0], active: false } });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);

    await user.click((await screen.findAllByTestId("atlas-memory-rule-toggle"))[0]);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0][1]).toEqual({ active: false });
    expect(del).not.toHaveBeenCalled();
  });

  it("delete sends DELETE and then re-reads — nothing is hidden client-side", async () => {
    serves(RULES);
    del.mockResolvedValue({ status: 204 });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);

    // After the delete the server has one rule left; the list must show that,
    // and must show it because the SERVER said so, not because this app spliced
    // a row out of its own state.
    serves([RULES[1]]);
    await user.click((await screen.findAllByTestId("atlas-memory-rule-delete"))[0]);

    await waitFor(() => expect(del).toHaveBeenCalledWith(`/atlas/memory/${RULES[0].id}`));
    await waitFor(() =>
      expect(screen.getAllByTestId("atlas-memory-rule")).toHaveLength(1)
    );
  });

  it("a failed delete says so and leaves the rule on screen", async () => {
    serves(RULES);
    del.mockRejectedValue({ response: { data: { detail: "No such rule" } } });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    await user.click((await screen.findAllByTestId("atlas-memory-rule-delete"))[0]);
    expect(await screen.findByTestId("atlas-memory-error")).toHaveTextContent("No such rule");
    expect(screen.getAllByTestId("atlas-memory-rule")).toHaveLength(2);
  });
});

describe("D12 suggests and never writes", () => {
  it("renders the suggestion in its own list, separate from the rules", async () => {
    serves(RULES, [SUGGESTION]);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    const offered = await screen.findAllByTestId("atlas-memory-suggestion");
    expect(offered).toHaveLength(1);
    // Rendered, not merged: a suggestion that appeared among the rules would
    // look like something ATLAS had already decided.
    expect(screen.getAllByTestId("atlas-memory-rule")).toHaveLength(2);
    expect(offered[0]).toHaveTextContent(SUGGESTION.text);
  });

  it("writes nothing until the user accepts, and then writes the server's own sentence", async () => {
    serves(RULES, [SUGGESTION]);
    post.mockResolvedValue({ data: RULES[0] });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    // Nothing has been written merely by rendering the offer.
    expect(post).not.toHaveBeenCalled();

    await user.click(await screen.findByTestId("atlas-memory-suggestion-accept"));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe("/atlas/memory");
    expect(post.mock.calls[0][1]).toEqual({ text: SUGGESTION.text });
  });

  it("prints the server's count and does nothing arithmetic with it", async () => {
    serves(RULES, [SUGGESTION]);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    expect(await screen.findByTestId("atlas-memory-suggestion-count")).toHaveTextContent("41");
  });
});

describe("D40 — a derived observation is not a memory rule", () => {
  it("has exactly one source of rows, and it is the server's `rules`", async () => {
    serves(RULES);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await openPanel(user);
    // One read, one path. A vendor baseline could only appear in this list by
    // arriving inside `rules` — which the backend asserts it never does
    // (`test_no_emitter_writes_to_the_memory_store`). There is no second fetch
    // here to merge one in from, and this assertion fails the day somebody adds
    // one.
    expect(get.mock.calls.map((call) => call[0])).toEqual(["/atlas/memory"]);
  });

  it("says on the screen why the list is shorter than a user might expect", async () => {
    serves([]);
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await user.click(await screen.findByTestId("atlas-memory-toggle"));
    // Without this sentence, a user who saw ATLAS quote a vendor's usual range
    // and cannot find it here will conclude the list is incomplete.
    expect(await screen.findByTestId("atlas-memory-scope")).toHaveTextContent(MEMORY_SCOPE_NOTE);
  });
});

describe("telling ATLAS something (§7.2, source `told`)", () => {
  it("posts the sentence exactly as typed, and names no provenance", async () => {
    serves([]);
    post.mockResolvedValue({ data: RULES[0] });
    const user = userEvent.setup();
    render(<MemoryPanel />);
    await user.click(await screen.findByTestId("atlas-memory-toggle"));
    const box = await screen.findByTestId("atlas-memory-new-text");
    await user.type(box, "Ignore rounding under 1 rupee.");
    await user.click(await screen.findByTestId("atlas-memory-new-save"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    // `source` is the backend's to set. A client that could name its own
    // provenance could label a lesson it invented as one the user gave.
    expect(post.mock.calls[0][1]).toEqual({ text: "Ignore rounding under 1 rupee." });
  });
});
