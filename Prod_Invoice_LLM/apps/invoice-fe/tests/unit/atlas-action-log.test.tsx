// =============================================================================
// FILE: tests/unit/atlas-action-log.test.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.7c (§5.3). FE Gap 701.
//
// §5.3 IS A BOUNDARY: "every write is visible, attributed and timestamped —
// what ATLAS did is a real list." These tests hold the FE half of it: the list
// is reachable, it carries who and when, and it carries the REFUSALS.
//
// THE REFUSAL TEST IS THE LOAD-BEARING ONE. A log of successes only answers
// "did ATLAS touch this invoice?" with a confident no on exactly the occasions
// someone is asking because something looks wrong. The backend writes a row
// before it raises (409/403/422); this asserts the screen shows it rather than
// filtering the failures out to look tidy.
//
// WHAT THIS CANNOT PROVE: that a row exists in Postgres. `apiClient` is mocked.
// The live evidence is in FE Feature 23 §15 — a refusal driven through a real
// backend and read back out of `atlas_action_log`.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const get = vi.fn();

vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    get: (...args: any[]) => get(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import ActionLog, {
  ACTION_LOG_EMPTY,
  OUTCOME_DID,
  OUTCOME_REFUSED,
} from "@/components/atlas/ActionLog";

/**
 * Newest first, as the backend orders them. Field for field this is
 * `ActionLogEntry` in `routers/atlas.py`; the values exercise both outcomes.
 */
const ENTRIES = [
  {
    id: "aaaaaaaa-0000-0000-0000-000000000001",
    recommendation_id: "train-arithmetic-8f2c3e91",
    kind: "apply_field_correction",
    target_id: "8f2c3e91-0000-0000-0000-000000000001",
    succeeded: false,
    summary:
      "I do not do 'apply_field_correction' for you. I can show you exactly where to do it, but being wrong here would not stay on one record.",
    user_id: "user_test_default",
    performed_at: "2026-09-18T07:10:00",
  },
  {
    id: "aaaaaaaa-0000-0000-0000-000000000002",
    recommendation_id: "approve-8f2c3e91-0001",
    kind: "resolve_invoice",
    target_id: "5004da49-0000-0000-0000-000000000001",
    succeeded: true,
    summary: "Invoice approved.",
    user_id: "user_second",
    performed_at: "2026-09-18T07:09:20",
  },
];

function serves(entries: unknown[]) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/actions") return Promise.resolve({ data: { entries } });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

/** Open the panel and wait for the ROWS, never for the container (FE Gap 641). */
async function openLog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId("atlas-action-log-toggle"));
  return screen.findAllByTestId("atlas-action-log-entry");
}

beforeEach(() => {
  get.mockReset();
});

describe("what ATLAS did is a real list a user can reach (§5.3)", () => {
  it("reads GET /atlas/actions and renders a row per attempt", async () => {
    serves(ENTRIES);
    const user = userEvent.setup();
    render(<ActionLog />);
    const rows = await openLog(user);
    expect(rows).toHaveLength(2);
    expect(get.mock.calls.map((call) => call[0])).toContain("/atlas/actions");
  });

  it("shows a REFUSAL as well as a success, with the refusal's reasoning", async () => {
    serves(ENTRIES);
    const user = userEvent.setup();
    render(<ActionLog />);
    const rows = await openLog(user);
    // The 409 row is first and is not filtered out. D50's reasoning rides in
    // `summary` and is printed as sent.
    expect(rows[0].dataset.succeeded).toBe("false");
    expect(rows[0]).toHaveTextContent(OUTCOME_REFUSED);
    expect(rows[0]).toHaveTextContent("being wrong here would not stay on one record");
    expect(rows[1].dataset.succeeded).toBe("true");
    expect(rows[1]).toHaveTextContent(OUTCOME_DID);
  });

  it("attributes and timestamps every row — §5.3's own two words", async () => {
    serves(ENTRIES);
    const user = userEvent.setup();
    render(<ActionLog />);
    await openLog(user);
    const who = await screen.findAllByTestId("atlas-action-log-user");
    const when = await screen.findAllByTestId("atlas-action-log-when");
    // Tenant-wide (BE §2.2): two different users appear in one list.
    expect(who.map((node) => node.textContent)).toEqual([
      "user_test_default",
      "user_second",
    ]);
    expect(when[0]).toHaveTextContent("2026-09-18T07:10:00");
  });

  it("never re-sorts the server's order", async () => {
    serves(ENTRIES);
    const user = userEvent.setup();
    render(<ActionLog />);
    await openLog(user);
    const kinds = await screen.findAllByTestId("atlas-action-log-kind");
    expect(kinds.map((node) => node.textContent)).toEqual([
      "apply_field_correction",
      "resolve_invoice",
    ]);
  });

  it("names the line each action came from — the part `audit_logs` does not answer", async () => {
    serves(ENTRIES);
    const user = userEvent.setup();
    render(<ActionLog />);
    await openLog(user);
    const lines = await screen.findAllByTestId("atlas-action-log-line");
    expect(lines[0]).toHaveTextContent("train-arithmetic-8f2c3e91");
  });

  it("re-reads when the panel is opened, so a just-performed action is there", async () => {
    serves([]);
    const user = userEvent.setup();
    render(<ActionLog />);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    serves(ENTRIES);
    const rows = await openLog(user);
    expect(rows).toHaveLength(2);
  });

  it("distinguishes an empty record from an unreadable one", async () => {
    serves([]);
    const user = userEvent.setup();
    render(<ActionLog />);
    await user.click(await screen.findByTestId("atlas-action-log-toggle"));
    expect(await screen.findByTestId("atlas-action-log-empty")).toHaveTextContent(
      ACTION_LOG_EMPTY
    );

    get.mockRejectedValue({ response: { data: { detail: "backend is down" } } });
    await user.click(await screen.findByTestId("atlas-action-log-refresh"));
    expect(await screen.findByTestId("atlas-action-log-error")).toHaveTextContent(
      "backend is down"
    );
  });
});
