// =============================================================================
// FILE: tests/unit/atlas-d47-d49.test.tsx
// FEATURE: FE Feature 23 — the three founder rulings of 2026-09-18.
//
// D47 — Verify stops promising what it cannot do (closes FE Gap 640).
// D48 — the ATLAS / traditional toggle beside the notification bell.
// D49 — a dismiss control on every line, and the dismissal persists.
//
// WHAT THESE TESTS CANNOT PROVE, said plainly so nobody reads them as more than
// they are: a unit test with a mocked `apiClient` cannot prove a dismissal
// survives a recompute. That is a property of the database and the router, and
// it is proven by `apps/invoice-be/tests/test_atlas_dismissals.py` against real
// Postgres and by the live end-to-end run recorded in the spec. What IS proven
// here is the FE's half of the contract: the click posts, and the screen
// re-reads instead of hiding the row itself.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const get = vi.fn();
const post = vi.fn();
const push = vi.fn();
let pathname = "/dashboard";

vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    get: (...args: any[]) => get(...args),
    post: (...args: any[]) => post(...args),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(),
}));

import AtlasLine from "@/components/atlas/AtlasLine";
import AtlasModeToggle from "@/components/layout/AtlasModeToggle";
import WorkScreen from "@/components/atlas/WorkScreen";
import { ATLAS_MODE_STORAGE_KEY } from "@/hooks/useAtlasMode";
import { VERIFY_ATTACH_HINT } from "@/lib/atlas";
import { auditLine, linesResponse, loaderLine } from "./atlas-fixtures";

function servesLines(payload: unknown) {
  get.mockImplementation((path: string) => {
    if (path === "/atlas/lines") return Promise.resolve({ data: payload });
    if (path === "/documents") return Promise.resolve({ data: [] });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  push.mockReset();
  pathname = "/dashboard";
  window.localStorage.clear();
});

// ═════════════════════════════════════════════════════════════════════════════
// D47 — the promise changed, not the plumbing
// ═════════════════════════════════════════════════════════════════════════════

describe("D47: Verify tells the user to attach and compare in chat", () => {
  it("says who attaches the document when the line names one", () => {
    const line = {
      ...auditLine,
      verify: { question: "Attach it here — is the total right?", document_id: "doc-1" },
    };
    render(
      <ul>
        <AtlasLine line={line} />
      </ul>
    );

    expect(screen.getByTestId("atlas-line-verify-hint")).toHaveTextContent(
      VERIFY_ATTACH_HINT
    );
    // The hint is an instruction to the user, not a claim about ATLAS.
    expect(VERIFY_ATTACH_HINT).toMatch(/attach the document in chat/i);
    expect(VERIFY_ATTACH_HINT).toMatch(/i do not attach it for you/i);
  });

  it("says nothing about attaching when there is no document to attach", () => {
    const line = {
      ...auditLine,
      verify: { question: "Which invoices make up this number?", document_id: null },
    };
    render(
      <ul>
        <AtlasLine line={line} />
      </ul>
    );

    expect(screen.queryByTestId("atlas-line-verify-hint")).toBeNull();
  });

  it("still opens chat seeded with the line's own question, and attaches nothing", () => {
    const line = {
      ...auditLine,
      verify: { question: "Attach it here — is the total right?", document_id: "doc-1" },
    };
    render(
      <ul>
        <AtlasLine line={line} />
      </ul>
    );

    const link = screen.getByTestId("atlas-line-verify");
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("/chat?seed=");
    // `URLSearchParams` encodes a space as `+`, so the query is parsed rather
    // than string-matched -- otherwise this asserts the encoder, not the seed.
    const seeded = new URLSearchParams(href.split("?")[1]);
    expect(seeded.get("seed")).toBe(line.verify.question);
    expect(seeded.get("verify_document_id")).toBe("doc-1");
    // FE Gap 640's rejected workaround: no upload, no copy, no attachment call.
    expect(post).not.toHaveBeenCalled();
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// D48 — the toggle beside the bell
// ═════════════════════════════════════════════════════════════════════════════

describe("D48: the ATLAS / traditional toggle", () => {
  it("starts on the traditional screens when nothing is stored", async () => {
    render(<AtlasModeToggle />);
    const toggle = await screen.findByTestId("atlas-mode-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveAttribute("data-mode", "classic");
  });

  it("remembers ATLAS mode in localStorage and goes to the work screen", async () => {
    render(<AtlasModeToggle />);
    const toggle = await screen.findByTestId("atlas-mode-toggle");

    await userEvent.click(toggle);

    await waitFor(() =>
      expect(window.localStorage.getItem(ATLAS_MODE_STORAGE_KEY)).toBe("atlas")
    );
    expect(push).toHaveBeenCalledWith("/work");
    expect(await screen.findByTestId("atlas-mode-toggle")).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("reads the stored choice back on mount", async () => {
    window.localStorage.setItem(ATLAS_MODE_STORAGE_KEY, "atlas");
    render(<AtlasModeToggle />);
    const toggle = await screen.findByTestId("atlas-mode-toggle");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("leaves the user where they are when switching back from a non-ATLAS route", async () => {
    window.localStorage.setItem(ATLAS_MODE_STORAGE_KEY, "atlas");
    pathname = "/invoices";
    render(<AtlasModeToggle />);
    const toggle = await screen.findByTestId("atlas-mode-toggle");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));

    await userEvent.click(toggle);

    await waitFor(() =>
      expect(window.localStorage.getItem(ATLAS_MODE_STORAGE_KEY)).toBe("classic")
    );
    // D48: the existing screens are not re-homed and nothing redirects away
    // from them. Only someone standing on /work has to be moved.
    expect(push).not.toHaveBeenCalled();
  });

  it("returns a user standing on the work screen to the app's own landing page", async () => {
    window.localStorage.setItem(ATLAS_MODE_STORAGE_KEY, "atlas");
    pathname = "/work";
    render(<AtlasModeToggle />);
    const toggle = await screen.findByTestId("atlas-mode-toggle");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));

    await userEvent.click(toggle);

    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("stores nothing but the mode — there is no preference API call", async () => {
    render(<AtlasModeToggle />);
    await userEvent.click(await screen.findByTestId("atlas-mode-toggle"));
    // D48: localStorage only. No per-user preference store exists and none was
    // built for this.
    expect(post).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// D49 — dismiss, on every line
// ═════════════════════════════════════════════════════════════════════════════

describe("D49: the dismiss control", () => {
  it("is on every line, whatever its capability", async () => {
    servesLines(linesResponse([auditLine, loaderLine]));
    render(<WorkScreen />);

    await waitFor(async () =>
      expect(await screen.findAllByTestId("atlas-line")).toHaveLength(2)
    );
    expect(screen.getAllByTestId("atlas-line-dismiss")).toHaveLength(2);
  });

  it("posts the dismissal and then RE-READS, rather than hiding the row", async () => {
    // The server's second answer is the one without the line. If the FE were
    // filtering locally this test would pass with `post` never called, so the
    // assertions below check both halves.
    const full = linesResponse([auditLine, loaderLine]);
    const afterDismiss = linesResponse([loaderLine]);
    let call = 0;
    get.mockImplementation((path: string) => {
      if (path === "/atlas/lines") {
        call += 1;
        return Promise.resolve({ data: call === 1 ? full : afterDismiss });
      }
      if (path === "/documents") return Promise.resolve({ data: [] });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    post.mockResolvedValue({
      data: { recommendation_id: auditLine.id, dismissed: true, created: true },
    });

    render(<WorkScreen />);
    await waitFor(async () =>
      expect(await screen.findAllByTestId("atlas-line")).toHaveLength(2)
    );

    await userEvent.click(screen.getAllByTestId("atlas-line-dismiss")[0]);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        `/atlas/lines/${encodeURIComponent(auditLine.id)}/dismiss`
      )
    );
    // The second read is what removed the line — not this component.
    await waitFor(() => expect(call).toBe(2));
    await waitFor(() =>
      expect(screen.getAllByTestId("atlas-line")).toHaveLength(1)
    );
    expect(
      screen.queryByText(auditLine.what.headline)
    ).toBeNull();
  });

  it("says so when the dismissal fails, instead of pretending the line is gone", async () => {
    servesLines(linesResponse([auditLine]));
    post.mockRejectedValue({ response: { data: { detail: "nope" } } });

    render(<WorkScreen />);
    await screen.findByTestId("atlas-line");

    await userEvent.click(screen.getByTestId("atlas-line-dismiss"));

    expect(await screen.findByTestId("work-screen-error")).toHaveTextContent("nope");
    expect(screen.getAllByTestId("atlas-line")).toHaveLength(1);
  });
});
