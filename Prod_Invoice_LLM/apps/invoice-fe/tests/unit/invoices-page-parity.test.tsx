/**
 * FE Feature 22 Task 22.2 — the Audit Queue page (`/invoices`) must behave
 * exactly as before its ledger logic moved into `hooks/useInvoiceLedger.ts`, so
 * that Records and the classic layout (22.21) render the same ledger.
 *
 * Same method as invoice-table-parity.test.tsx: the snapshots were recorded
 * against the ORIGINAL page before the refactor and were not re-recorded. Two
 * things are pinned — the rendered markup at each step of a click-through, and
 * the multiset of backend calls (URL + params) the page made. Call ORDER is
 * deliberately not pinned: it is scheduling, not behaviour.
 *
 * The click-through also pins the one property a naive per-pane extraction
 * would break: switching Receiving -> Sending -> Receiving keeps the inbound
 * tab and page the user left, because ledger state lives above the panes.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";

const api = vi.hoisted(() => ({ calls: [] as string[] }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
    get: vi.fn(async (url: string, config?: { params?: Record<string, unknown> }) => {
      api.calls.push(`${url} ${JSON.stringify(config?.params ?? {})}`);
      const params = config?.params ?? {};
      if (url === "/invoices") {
        const rows = [
          { id: `in-${String(params.offset ?? 0)}`, invoice_number: `IN-${String(params.status ?? params.status_in ?? "ALL")}`, vendor_name: "Rajesh Steel", status: "PAID", tags: ["steel"] },
        ];
        return { data: rows, headers: { "x-total-count": "20" } };
      }
      if (url === "/outbound-dashboard/invoices") {
        const rows = [
          { id: `out-${String(params.offset ?? 0)}`, invoice_number: `OUT-${String(params.status ?? params.status_in ?? "ALL")}`, customer_name: "Kaveri", status: "VERIFIED" },
        ];
        return { data: rows, headers: { "x-total-count": "11" } };
      }
      throw new Error(`unexpected GET ${url}`);
    }),
  },
}));

import InvoicesPage from "@/app/invoices/page";
import { PageHeaderProvider, usePageHeaderActionsRef } from "@/components/layout/PageHeaderContext";

function HeaderSlot() {
  return <div data-testid="header-actions" ref={usePageHeaderActionsRef()} />;
}

function serviceFlow(receive: boolean, send: boolean) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/settings/service-flow") {
      return new Response(JSON.stringify({ receive_invoices_enabled: receive, send_invoices_enabled: send }), {
        status: 200,
      });
    }
    throw new Error(`unexpected fetch ${String(input)}`);
  });
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function renderPage() {
  return render(
    <PageHeaderProvider>
      <HeaderSlot />
      <InvoicesPage />
    </PageHeaderProvider>
  );
}

beforeEach(() => {
  api.calls = [];
  window.localStorage.clear();
});

describe("/invoices (Audit Queue) — parity through the ledger extraction", () => {
  it("receive only: inbound ledger, no outbound calls", async () => {
    serviceFlow(true, false);
    const { container } = renderPage();
    await screen.findByText("IN-ALL");
    await settle();

    expect(container.innerHTML).toMatchSnapshot("markup");
    expect([...api.calls].sort()).toMatchSnapshot("calls");
  });

  it("both directions: tabs, paging, pane switching and preserved state", async () => {
    serviceFlow(true, true);
    const { container } = renderPage();
    await screen.findByText("IN-ALL");
    await settle();
    const header = screen.getByTestId("header-actions");

    fireEvent.click(screen.getByRole("button", { name: "Paid" }));
    await screen.findByText("IN-PAID");
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await screen.findByText("Page 2 of 3 (20 invoices)");
    await settle();

    fireEvent.click(within(header).getByRole("button", { name: "Sending" }));
    await screen.findByText("OUT-ALL");
    fireEvent.click(screen.getByRole("button", { name: "Overdue" }));
    await screen.findByText("OUT-overdue");
    await settle();
    expect(container.innerHTML).toMatchSnapshot("sending pane, overdue tab");

    fireEvent.click(within(header).getByRole("button", { name: "Receiving" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3 (20 invoices)")).toBeInTheDocument());
    await settle();
    expect(container.innerHTML).toMatchSnapshot("back on receiving, state kept");
    expect([...api.calls].sort()).toMatchSnapshot("calls");
  });
});
