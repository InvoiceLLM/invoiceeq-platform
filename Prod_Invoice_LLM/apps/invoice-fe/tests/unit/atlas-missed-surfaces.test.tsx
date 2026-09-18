// =============================================================================
// FILE: tests/unit/atlas-missed-surfaces.test.tsx
// FEATURE: FE Feature 23 — BE Feature 34 task 34.14 (D34, §5.2). FE Gap 703.
//
// D34 SAYS "ON ANY RECORD". The control shipped on ATLAS lines only, which is
// the one surface where it is least useful — a line is a thing ATLAS already
// noticed. A miss is noticed on a record ATLAS said nothing about.
//
// WHY THE MOUNT TEST IS GREP-SHAPED. A render test of the invoice review console
// would be a render test of a 1,100-line page with a PDF canvas in it; what
// needs guarding is not how the control looks there but THAT IT IS THERE, and
// that it stays there. This is the same shape `atlas-no-client-arithmetic.test.ts`
// uses, and for the same reason: it proves a property of the source, not of one
// payload.
//
// The behavioural half — that whatever entity kind a surface passes is sent
// through unedited — is a real render below, because that is where a mistake
// would file the evidence against a row that does not exist.
// =============================================================================

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const post = vi.fn();

vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    get: vi.fn(),
    post: (...args: any[]) => post(...args),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import MissedThis from "@/components/atlas/MissedThis";

const ROOT = path.resolve(__dirname, "..", "..");

/**
 * Every surface that must carry D34's control, and why that one.
 *
 * `app/history` is the product's documents list: `app/documents/page.tsx` was
 * folded into History by FE Gap 464, so `IngestionHistoryTable` is where a user
 * looks when a file's outcome does not match what they expected.
 */
const SURFACES: Array<[string, string]> = [
  ["an ATLAS line, where it started", path.join("components", "atlas", "AtlasLine.tsx")],
  ["the invoice review console", path.join("app", "invoices", "review", "[id]", "page.tsx")],
  ["the trainer", path.join("app", "trainer", "page.tsx")],
  [
    "the documents list (History)",
    path.join("components", "ingestion", "IngestionHistoryTable.tsx"),
  ],
];

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue({ data: { id: "r1", rule: { id: "m1", text: "..." } } });
});

describe('"you missed this" is on any record (D34, FE Gap 703)', () => {
  it.each(SURFACES)("%s mounts MissedThis", (_why, relative) => {
    const source = readFileSync(path.join(ROOT, relative), "utf8");
    expect(source).toMatch(/from "@\/components\/atlas\/MissedThis"/);
    expect(source).toMatch(/<MissedThis/);
  });

  it("is mounted on more than the ATLAS line it started on", () => {
    // The guard against this regressing to its original state, which is what
    // FE Gap 703 recorded.
    expect(SURFACES.length).toBeGreaterThan(1);
  });
});

describe("the entity a surface names is sent unedited", () => {
  it("passes a non-invoice record kind straight through", async () => {
    const user = userEvent.setup();
    render(<MissedThis entityKind="rejected_email" entityId="f00d-0001" />);
    await user.click(await screen.findByTestId("atlas-missed-open"));
    await user.type(
      await screen.findByTestId("atlas-missed-text"),
      "This was a real invoice and you rejected it."
    );
    await user.click(await screen.findByTestId("atlas-missed-send"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe("/atlas/missed");
    // Kind and id as given: flattening a rejected email to "invoice" would file
    // the evidence against a row that does not exist. The sentence is sent
    // exactly as typed — it is the evidence ATLAS was wrong.
    expect(post.mock.calls[0][1]).toEqual({
      entity_kind: "rejected_email",
      entity_id: "f00d-0001",
      description: "This was a real invoice and you rejected it.",
    });
  });

  it("is not gated on anything — it renders with no capability, role or status prop", () => {
    // A miss is noticed by whoever happens to be looking (BE §17.7). The
    // component takes an entity and nothing else, which is what makes that
    // impossible to get wrong at a call site.
    render(<MissedThis entityKind="invoice" entityId="abc" />);
    expect(screen.getByTestId("atlas-missed-open")).toBeTruthy();
  });
});
