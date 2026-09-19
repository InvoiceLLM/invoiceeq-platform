// =============================================================================
// FILE: tests/unit/atlas-destinations.test.tsx
// FEATURE: FE Feature 23 — BE Feature 34 D50 (suggest-only destinations).
//          FE Gap 702.
//
// THIS FILE EXISTS TO TEST A SEAM, NOT A FUNCTION. FE Gap 702 was filed rather
// than worked around because the tempting fix — append a query string and stop —
// produces exactly the F33/F22 defect: a parameter one side sends and no page
// reads, which looks like the feature works while doing nothing.
//
// So the tests below deliberately do NOT assert "actionDestination returns
// /invoices?status=PROCESSING" and leave it there. They take the URL that
// function produces, hand it to the real `/invoices` page as its search params,
// and assert the page then ASKS THE BACKEND for the filtered set. If either end
// is changed alone, this goes red — which is the only kind of test that can
// close this defect class.
//
// WHAT IT CANNOT PROVE: that the backend honours `status` / `vendor_name`.
// `apiClient` is mocked. That half is proven live, in FE Feature 23 §15.
// =============================================================================

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

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

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ loading: false, user: { role: "Admin" } }),
  refreshAuth: vi.fn(),
}));

vi.mock("@/components/layout/PageHeaderContext", () => ({
  usePageHeader: () => undefined,
  PageHeaderActions: ({ children }: { children?: any }) => children ?? null,
}));

/** The page's own search params, supplied per test from a real destination URL. */
let SEARCH = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/invoices",
  useSearchParams: () => SEARCH,
}));

import InvoicesPage from "@/app/invoices/page";
import {
  actionDestination,
  INVOICE_STATUS_PARAM,
  INVOICE_VENDOR_PARAM,
  STUCK_INVOICE_STATUS,
  type AtlasRecommendation,
} from "@/lib/atlas";
import { auditLine } from "./atlas-fixtures";

/** A line of the given kind, otherwise a real payload shape. */
function lineOfKind(kind: string, targetId: string): AtlasRecommendation {
  return {
    ...auditLine,
    action: { ...auditLine.action, kind, target_id: targetId },
  };
}

/** Split a destination into the path the app routes to and the query it carries. */
function destinationOf(line: AtlasRecommendation): { path: string; query: URLSearchParams } {
  const href = actionDestination(line);
  expect(href).not.toBeNull();
  const url = new URL(href as string, "http://localhost"); // hardcode-ok: a parsing base, never fetched
  return { path: url.pathname, query: url.searchParams };
}

/** The params of the paged `/invoices` read the list page performs. */
async function pagedRequestParams(): Promise<Record<string, unknown>> {
  await waitFor(() => {
    const paged = get.mock.calls.find(
      (call) => call[0] === "/invoices" && call[1]?.params?.limit !== 100
    );
    expect(paged).toBeTruthy();
  });
  const paged = get.mock.calls.find(
    (call) => call[0] === "/invoices" && call[1]?.params?.limit !== 100
  );
  return paged?.[1]?.params ?? {};
}

beforeEach(() => {
  get.mockReset();
  get.mockResolvedValue({ data: [], headers: {} });
  SEARCH = new URLSearchParams();
  // The page asks for the tenant's service-flow config on mount.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ receive_invoices_enabled: true, send_invoices_enabled: false }),
    }))
  );
});

describe("a suggest-only destination carries a filter (D50, FE Gap 702)", () => {
  it("'open the stuck list' names the status its own emitter selected on", () => {
    const { path, query } = destinationOf(lineOfKind("requeue_invoices", "tenant-1"));
    expect(path).toBe("/invoices");
    // `services/atlas_skills.py::_stuck_in_processing` filters status ==
    // "PROCESSING". The FE constant exists so a grep finds both halves.
    expect(query.get(INVOICE_STATUS_PARAM)).toBe(STUCK_INVOICE_STATUS);
  });

  it("'review these against payments' names the vendor the recon put in target_id", () => {
    const { path, query } = destinationOf(
      lineOfKind("review_unlisted_invoices", "Kumar Supplies & Co")
    );
    expect(path).toBe("/invoices");
    expect(query.get(INVOICE_VENDOR_PARAM)).toBe("Kumar Supplies & Co");
  });

  it("invents no parameter for the exact invoice set, because no page reads one", () => {
    // Both kinds carry `params.invoice_ids`. `GET /invoices` has no id-set
    // filter, so sending one would be the very defect this gap was filed for.
    const { query } = destinationOf(lineOfKind("requeue_invoices", "tenant-1"));
    expect(query.get("invoice_ids")).toBeNull();
    expect(query.get("ids")).toBeNull();
  });

  it("leaves the kinds that are instructions with no destination at all", () => {
    expect(actionDestination(lineOfKind("attach_witness_document", "doc-1"))).toBeNull();
    expect(actionDestination(lineOfKind("request_missing_invoices", "vendor-1"))).toBeNull();
  });
});

describe("the other end of the seam: /invoices reads what ATLAS sends", () => {
  it("lands filtered to the stuck invoices, not on the whole list", async () => {
    SEARCH = destinationOf(lineOfKind("requeue_invoices", "tenant-1")).query;
    render(<InvoicesPage />);
    const params = await pagedRequestParams();
    // The request the page actually makes — this is what "the destination
    // filters" has to mean.
    expect(params.status).toBe(STUCK_INVOICE_STATUS);
  });

  it("lands filtered to the vendor whose statement did not list them", async () => {
    SEARCH = destinationOf(
      lineOfKind("review_unlisted_invoices", "Kumar Supplies & Co")
    ).query;
    render(<InvoicesPage />);
    const params = await pagedRequestParams();
    expect(params.vendor_name).toBe("Kumar Supplies & Co");
  });

  it("is the unfiltered list when no parameter is sent", async () => {
    render(<InvoicesPage />);
    const params = await pagedRequestParams();
    expect(params.status).toBeUndefined();
    expect(params.vendor_name).toBeUndefined();
  });
});
