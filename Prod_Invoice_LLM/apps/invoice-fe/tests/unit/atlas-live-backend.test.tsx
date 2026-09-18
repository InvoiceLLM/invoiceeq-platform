// =============================================================================
// FILE: tests/unit/atlas-live-backend.test.tsx
// FEATURE: FE Feature 23 §10, the last invariant — **the screen renders from a
//          real backend response, not a fixture.**
//
// WHY THIS FILE EXISTS AT ALL: Feature 33 shipped 118/118 passing tests over ten
// dead capabilities, and FE Feature 22 specified a live event that neither side
// ever published. Every other test in this feature proves the screen renders
// what it is handed. This one proves what it is handed is real: it calls a
// RUNNING invoice-be, takes the bytes that come back, and renders the work
// screen from them with no shaping in between.
//
// OPT-IN, AND LOUD ABOUT IT. It runs when `ATLAS_LIVE_URL` names a backend
// (e.g. `http://127.0.0.1:8077`) and is otherwise SKIPPED with the reason —
// CI has no backend, and a test that silently passed without one would be the
// exact thing it exists to prevent. When the variable IS set and the backend
// does not answer, it FAILS rather than skipping: BE Gap 697's rule, that a
// test which hides itself is worse than a test that is red.
//
//   $ (cd ../invoice-be && DATABASE_URL=postgresql://…@127.0.0.1:5433/invoice_db \
//        ALLOW_MOCK_AUTH=true ./.venv/Scripts/python.exe -m uvicorn main:app --port 8077)
//   $ ATLAS_LIVE_URL=http://127.0.0.1:8077 npx vitest run tests/unit/atlas-live-backend.test.tsx
// =============================================================================

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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

import WorkScreen from "@/components/atlas/WorkScreen";
import { lineDefect, type AtlasLinesResponse } from "@/lib/atlas";

const BASE = process.env.ATLAS_LIVE_URL;
const live = BASE ? describe : describe.skip;

let payload: AtlasLinesResponse;

live("the work screen renders from a live backend response", () => {
  beforeAll(async () => {
    const response = await fetch(`${BASE}/api/v1/atlas/lines`).catch((err) => {
      throw new Error(
        `ATLAS_LIVE_URL is set to ${BASE} but the backend did not answer: ${err}. ` +
          `This is a failure, not a skip — see BE Gap 697.`
      );
    });
    if (!response.ok) {
      throw new Error(
        `GET ${BASE}/api/v1/atlas/lines answered ${response.status}: ${await response.text()}`
      );
    }
    payload = (await response.json()) as AtlasLinesResponse;
  });

  // Re-armed per test, not once in beforeAll: `vitest.setup.ts` runs
  // `vi.restoreAllMocks()` after every test, so an implementation set once would
  // survive exactly one of them -- and the rest would render the failure state
  // while looking like a backend problem.
  beforeEach(() => {
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines") return Promise.resolve({ data: payload });
      return Promise.resolve({ data: [] });
    });
  });

  it("gets the envelope this FE was written against, key for key", () => {
    // The seam, checked directly: the FE reads these five names and the backend
    // must send all five. A missing key here is the F33/F22 defect arriving.
    for (const key of [
      "ungranted",
      "capabilities",
      "lines",
      "doubt_checks_run",
      "doubt_checks_skipped",
    ]) {
      expect(payload, `the live envelope has no ${key}`).toHaveProperty(key);
    }
  });

  it("serves lines that pass the FE's own completeness check", () => {
    expect(
      payload.lines.length,
      "the live backend returned no lines at all — seed the tenant before trusting this run"
    ).toBeGreaterThan(0);
    for (const line of payload.lines) {
      expect(lineDefect(line), `live line ${line.id} is incomplete`).toBeNull();
    }
  });

  it("renders every live line on the screen, with its own headline and reason", async () => {
    render(<WorkScreen />);

    await waitFor(() =>
      expect(screen.getAllByTestId("atlas-line")).toHaveLength(payload.lines.length)
    );
    expect(screen.queryAllByTestId("atlas-line-defect")).toHaveLength(0);

    for (const line of payload.lines) {
      expect(screen.getByText(line.what.headline)).toBeInTheDocument();
      expect(screen.getByText(line.why.text)).toBeInTheDocument();
      expect(screen.getByText(line.verify.question)).toBeInTheDocument();
    }
  });

  it("prints the live figures exactly as the backend rendered them", async () => {
    render(<WorkScreen />);
    await waitFor(() => expect(screen.getAllByTestId("atlas-line").length).toBeGreaterThan(0));

    const figures = payload.lines.flatMap((line) => line.why.figures);
    expect(figures.length).toBeGreaterThan(0);
    for (const figure of figures) {
      // `rendered` and nothing else: if the screen had reformatted or rounded a
      // live amount, this is where it would show.
      expect(screen.getAllByText(figure.rendered).length).toBeGreaterThan(0);
    }
  });
});
