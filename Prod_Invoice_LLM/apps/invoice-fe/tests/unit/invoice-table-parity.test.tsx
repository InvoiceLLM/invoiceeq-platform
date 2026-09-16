/**
 * FE Feature 22 Task 22.2 — parity for the table unification and the builder
 * extraction.
 *
 * HOW THIS PROVES PARITY. The snapshots in __snapshots__/ were first recorded
 * against the ORIGINAL `RecentInvoicesTable`, `OutboundInvoicesTable` and
 * outbound-builder page, before any 22.2 change landed. The refactor was then
 * required to reproduce them byte for byte WITHOUT re-recording (`-u` was not
 * run). So "the unified table renders the same rows for direction=in as
 * RecentInvoicesTable did on the same fixture" (spec §6, 22.2) is asserted
 * against the old component's own output, not against a description of it.
 *
 * `renderInbound` / `renderOutbound` / `renderBuilderPage` are the only seams:
 * they pointed at the old components when the snapshots were recorded and
 * point at the unified ones now.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

const nav = vi.hoisted(() => ({ push: vi.fn(), source: "11111111-1111-1111-1111-111111111111" as string | null }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: vi.fn() }),
  useSearchParams: () => ({ get: (key: string) => (key === "source" ? nav.source : null) }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/apiClient", () => ({ apiClient: { delete: vi.fn(), get: vi.fn() } }));

import InvoiceTable, {
  type InvoiceRecord,
  type InvoiceTableProps,
  type OutboundInvoiceRecord,
} from "@/components/records/InvoiceTable";
import OutboundBuilderPage from "@/app/invoices/outbound-builder/page";
import { PageHeaderProvider, usePageHeaderActionsRef } from "@/components/layout/PageHeaderContext";

type InboundProps = Omit<Extract<InvoiceTableProps, { direction: "in" }>, "direction">;
type OutboundProps = Omit<Extract<InvoiceTableProps, { direction: "out" }>, "direction">;

function renderInbound(props: InboundProps) {
  return render(<InvoiceTable direction="in" {...props} />);
}

function renderOutbound(props: OutboundProps) {
  return render(<InvoiceTable direction="out" {...props} />);
}

function HeaderSlot() {
  return <div data-testid="header-actions" ref={usePageHeaderActionsRef()} />;
}

function renderBuilderPage() {
  return render(
    <PageHeaderProvider>
      <HeaderSlot />
      <OutboundBuilderPage />
    </PageHeaderProvider>
  );
}

const INBOUND: InvoiceRecord[] = [
  {
    id: "a1",
    invoice_number: "RAJ-2008",
    vendor_name: "Rajesh Steel",
    invoice_date: "2026-08-02",
    created_at: "2026-08-03T09:00:00Z",
    due_date: "2026-09-01",
    grand_total: 220000,
    currency: "INR",
    status: "AUDIT_REQUIRED",
    tags: ["#steel", "q3"],
  },
  { id: "a2", status: "PROCESSING" },
  { id: "a3", invoice_number: "BH-11", vendor_name: "Bharat Hardware", grand_total: 103191, currency: "INR", status: "PAID" },
  { id: "a4", invoice_number: "DUP-1", status: "DUPLICATE", currency: null },
  { id: "a5", invoice_number: "X-9", status: "NEEDS_RESUBMISSION", grand_total: 12.5, currency: "USD" },
  { id: "a6", invoice_number: "R-1", status: "REJECTED" },
  { id: "a7", invoice_number: "L-1", status: "REVIEW_LATER" },
  { id: "a8", invoice_number: "F-1", status: "FAILED" },
  { id: "a9", invoice_number: "C-1", status: "COMPLETED" },
];

const OUTBOUND: OutboundInvoiceRecord[] = [
  { id: "b1", invoice_number: "INV-1042", customer_name: "Northwind", invoice_date: "2026-08-01", grand_total: 5000, currency: "USD", status: "VERIFIED" },
  { id: "b2", invoice_number: "INV-1043", customer_name: "Kaveri", status: "SENT", is_overdue: true, source_invoice_id: "b1" },
  { id: "b3", status: "PROCESSING_OCR" },
  { id: "b4", invoice_number: "INV-1044", status: "NEEDS_REVIEW", customer_name: "Acme" },
  { id: "b5", invoice_number: "INV-1045", status: "PAID", customer_name: "Acme", grand_total: 99, currency: "EUR" },
  { id: "b6", invoice_number: "INV-1046", status: "EXTRACTING_DATA" },
];

const noop = () => undefined;

beforeEach(() => {
  nav.push.mockReset();
  nav.source = "11111111-1111-1111-1111-111111111111";
});

describe("InvoiceTable direction=in — parity with RecentInvoicesTable", () => {
  const base: InboundProps = {
    invoices: INBOUND,
    isLoading: false,
    activeTab: "audit_required",
    onTabChange: noop,
    currentPage: 2,
    totalPages: 3,
    totalCount: 21,
    onPageChange: noop,
  };

  it("rows, full page", () => {
    expect(renderInbound({ ...base, isFullPage: true }).container.innerHTML).toMatchSnapshot();
  });

  it("rows, dashboard card", () => {
    expect(renderInbound(base).container.innerHTML).toMatchSnapshot();
  });

  it("loading", () => {
    expect(renderInbound({ ...base, isLoading: true }).container.innerHTML).toMatchSnapshot();
  });

  it("empty, single page", () => {
    expect(
      renderInbound({ ...base, invoices: [], totalPages: 1, totalCount: 0, currentPage: 1 }).container.innerHTML
    ).toMatchSnapshot();
  });

  it("a row click opens the review console", () => {
    renderInbound(base);
    fireEvent.click(screen.getByText("RAJ-2008"));
    expect(nav.push).toHaveBeenCalledWith("/invoices/review/a1");
  });
});

describe("InvoiceTable direction=out — parity with OutboundInvoicesTable", () => {
  const base: OutboundProps = {
    invoices: OUTBOUND,
    isLoading: false,
    activeTab: "overdue",
    onTabChange: noop,
    currentPage: 1,
    totalPages: 2,
    totalCount: 9,
    onPageChange: noop,
  };

  it("rows", () => {
    expect(renderOutbound(base).container.innerHTML).toMatchSnapshot();
  });

  it("loading", () => {
    expect(renderOutbound({ ...base, isLoading: true }).container.innerHTML).toMatchSnapshot();
  });

  it("empty", () => {
    expect(
      renderOutbound({ ...base, invoices: [], totalPages: 1, totalCount: 0 }).container.innerHTML
    ).toMatchSnapshot();
  });
});

describe("outbound builder page — parity after extracting OutboundBuilder", () => {
  const DEFAULTS = {
    source_invoice_id: "11111111-1111-1111-1111-111111111111",
    customer_name: "Northwind Traders",
    vendor_name: "E2E Co",
    invoice_number: "INV-1043",
    invoice_date: "2026-02-01T00:00:00",
    due_date: "2026-03-03",
    po_number: null,
    currency: "USD",
    tax_amount: "10.00",
    discount_percent: null,
    discount_amount: null,
    items: [{ description: "Consulting hours", quantity: "3", unit_price: "19.99" }],
  };

  function mockFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/build-defaults")) {
        return new Response(JSON.stringify(DEFAULTS), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/api/outbound-invoices/build")) {
        return new Response(JSON.stringify({ batch_id: "batch-9", invoice_id: "inv-new" }), { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
  }

  it("renders the loaded form and its header actions", async () => {
    mockFetch();
    const { container } = renderBuilderPage();
    await screen.findByTestId("create-invoice");
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("Create posts the form to the Feature 20 endpoint and routes to the Sending ledger", async () => {
    const fetchMock = mockFetch();
    renderBuilderPage();
    const create = await screen.findByTestId("create-invoice");
    await act(async () => {
      fireEvent.click(create);
    });

    await waitFor(() => expect(nav.push).toHaveBeenCalledTimes(1));
    const buildCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/outbound-invoices/build"));
    expect(buildCall?.[1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(buildCall?.[1]?.body))).toMatchObject({
      source_invoice_id: DEFAULTS.source_invoice_id,
      invoice_number: "INV-1043",
      invoice_date: "2026-02-01",
    });
    expect(nav.push).toHaveBeenCalledWith(
      "/ingestion?tab=sending&builtInvoice=inv-new&batch=batch-9&name=INV-1043"
    );
  });

  it("no ?source= is an explained error", async () => {
    nav.source = null;
    mockFetch();
    const { container } = renderBuilderPage();
    await screen.findByTestId("builder-load-error");
    expect(container.innerHTML).toMatchSnapshot();
  });
});
