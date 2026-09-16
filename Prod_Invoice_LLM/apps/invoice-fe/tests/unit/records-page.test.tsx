/**
 * FE Feature 22 Task 22.2 — Records.
 *
 * The ledger's own rendering is proven identical to the Audit Queue's by the two
 * parity suites; this file pins what is new to Records: `?tab=` selection,
 * Service-Flow tab visibility, and the builder as a drawer — opened in place
 * from a row, and submitting through Feature 20's own Create handler (same
 * endpoint, same body, same hand-off to the Sending ledger).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";

const nav = vi.hoisted(() => ({
  params: new URLSearchParams(),
  push: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
  useSearchParams: () => nav.params,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ loading: false, role: "Admin" }) }));
vi.mock("@/lib/apiClient", () => ({
  apiClient: {
    delete: vi.fn(),
    get: vi.fn(async (url: string) => {
      if (url === "/invoices") {
        return { data: [{ id: "a1", invoice_number: "RAJ-2008", vendor_name: "Rajesh Steel", status: "PAID" }], headers: { "x-total-count": "1" } };
      }
      if (url === "/outbound-dashboard/invoices") {
        return { data: [{ id: "b1", invoice_number: "INV-1042", customer_name: "Northwind", status: "VERIFIED" }], headers: { "x-total-count": "1" } };
      }
      throw new Error(`unexpected GET ${url}`);
    }),
  },
}));

import RecordsPage from "@/app/records/page";
import { apiClient } from "@/lib/apiClient";

const DEFAULTS = {
  source_invoice_id: "b1",
  customer_name: "Northwind",
  vendor_name: "E2E Co",
  invoice_number: "INV-1043",
  invoice_date: "2026-02-01",
  due_date: null,
  po_number: null,
  currency: "USD",
  tax_amount: null,
  discount_percent: null,
  discount_amount: null,
  items: [{ description: "Consulting", quantity: "1", unit_price: "10" }],
};

function mockFetch(flow: { receive: boolean; send: boolean }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/settings/service-flow") {
      return new Response(JSON.stringify({ receive_invoices_enabled: flow.receive, send_invoices_enabled: flow.send }), { status: 200 });
    }
    if (url === "/api/outbound-invoices/b1/build-defaults") {
      return new Response(JSON.stringify(DEFAULTS), { status: 200 });
    }
    if (url === "/api/outbound-invoices/build") {
      return new Response(JSON.stringify({ batch_id: "batch-1", invoice_id: "inv-2" }), { status: 200 });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
}

function tabs() {
  return within(screen.getByRole("tablist", { name: "Records" }))
    .getAllByRole("tab")
    .map((tab) => [tab.textContent, tab.getAttribute("aria-selected")]);
}

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.push.mockReset();
  nav.replace.mockReset();
  window.localStorage.clear();
});

describe("Records (22.2)", () => {
  it("defaults to Invoices in and shows all four tabs when both directions are on", async () => {
    mockFetch({ receive: true, send: true });
    render(<RecordsPage />);
    await screen.findByText("RAJ-2008");
    await waitFor(() =>
      expect(tabs()).toEqual([
        ["Invoices in", "true"],
        ["Invoices out", "false"],
        ["Documents", "false"],
        ["Rules", "false"],
      ])
    );
  });

  it("selects the tab named in ?tab= and switches tabs through the URL", async () => {
    nav.params = new URLSearchParams("tab=out");
    mockFetch({ receive: true, send: true });
    render(<RecordsPage />);
    await screen.findByText("INV-1042");
    expect(screen.queryByText("RAJ-2008")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));
    expect(nav.replace).toHaveBeenCalledWith("/records?tab=documents");
  });

  it("renders the Documents and Rules shells", async () => {
    mockFetch({ receive: true, send: true });
    nav.params = new URLSearchParams("tab=documents");
    const { unmount } = render(<RecordsPage />);
    expect(await screen.findByTestId("records-documents")).toBeInTheDocument();
    unmount();

    nav.params = new URLSearchParams("tab=rules");
    render(<RecordsPage />);
    expect(await screen.findByTestId("records-rules")).toBeInTheDocument();
  });

  it("hides a direction Service Flow has switched off, and never fetches outbound", async () => {
    nav.params = new URLSearchParams("tab=out");
    mockFetch({ receive: true, send: false });
    render(<RecordsPage />);

    await waitFor(() => expect(tabs().map(([name]) => name)).toEqual(["Invoices in", "Documents", "Rules"]));
    expect(await screen.findByText("RAJ-2008")).toBeInTheDocument();
    expect(vi.mocked(apiClient.get).mock.calls.some(([url]) => url === "/outbound-dashboard/invoices")).toBe(false);
  });

  it("the clone action opens the drawer in place rather than navigating to the builder page", async () => {
    nav.params = new URLSearchParams("tab=out");
    mockFetch({ receive: true, send: true });
    render(<RecordsPage />);

    const clone = await screen.findByTestId("clone-invoice-b1");
    expect(clone.tagName).toBe("BUTTON");
    fireEvent.click(clone);
    expect(nav.push).toHaveBeenCalledWith("/records?tab=out&source=b1");
  });

  it("?source= opens the drawer, and Create submits through Feature 20's handler", async () => {
    nav.params = new URLSearchParams("tab=out&source=b1");
    const fetchMock = mockFetch({ receive: true, send: true });
    render(<RecordsPage />);

    const drawer = await screen.findByRole("dialog", { name: "Invoice Builder" });
    const create = await within(drawer).findByTestId("create-invoice");
    expect(within(drawer).getByText("New invoice INV-1043")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(create);
    });
    await waitFor(() => expect(nav.push).toHaveBeenCalledTimes(1));

    const build = fetchMock.mock.calls.find(([url]) => String(url) === "/api/outbound-invoices/build");
    expect(build?.[1]).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" } });
    expect(JSON.parse(String(build?.[1]?.body))).toMatchObject({ source_invoice_id: "b1", invoice_number: "INV-1043" });
    expect(nav.push).toHaveBeenCalledWith("/ingestion?tab=sending&builtInvoice=inv-2&batch=batch-1&name=INV-1043");
  });

  it("Close and Escape both return to the outbound ledger", async () => {
    nav.params = new URLSearchParams("tab=out&source=b1");
    mockFetch({ receive: true, send: true });
    render(<RecordsPage />);

    const drawer = await screen.findByRole("dialog", { name: "Invoice Builder" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Close invoice builder" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/records?tab=out");

    nav.replace.mockReset();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(nav.replace).toHaveBeenCalledWith("/records?tab=out");
  });
});
