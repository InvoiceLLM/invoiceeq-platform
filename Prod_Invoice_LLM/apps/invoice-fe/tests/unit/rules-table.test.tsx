/**
 * FE Feature 22 Task 22.8 — Records › Rules.
 *
 * Spec §6: two vendor templates + one Global render as three groups; a vendor
 * with zero rules is absent; the tab renders exactly one link to
 * /settings/chat-rules and makes no `GET /chat/rules` call of its own.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import type { RuleVersion } from "@/lib/trainer-service";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({ apiClient: api }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import RulesTable, { ruleGroupsFrom } from "@/components/records/RulesTable";

function version(v: number, rules: string[], extra: Partial<RuleVersion> = {}): RuleVersion {
  return { id: `id-${v}`, version: v, scope: "global", rules, changedBy: "ops@acme", changedAt: "2026-09-10 10:00", ...extra };
}

const HISTORY: Record<string, RuleVersion[]> = {
  global: [version(2, ["Tax is GST, not VAT."], { isCurrent: true, templateId: "tpl-g" }), version(1, [], { templateId: "tpl-g" })],
  "Rajesh Steel": [version(4, ["Freight is not taxable.", "Due date is 45 days after invoice date."], { isCurrent: true, templateId: "tpl-r" }), version(3, ["Freight is not taxable."], { templateId: "tpl-r" })],
  "Bharat Hardware": [version(1, ["Invoice number is the 'Bill No.' field."], { isCurrent: true, templateId: "tpl-b" })],
  "Kaveri Traders": [version(2, [], { isCurrent: true, templateId: "tpl-k" })],
  "Northwind": [],
};

function mockBackend() {
  api.get.mockImplementation(async (url: string, config?: { params?: Record<string, string> }) => {
    if (url === "/trainer/vendors") {
      return { data: ["Rajesh Steel", "Kaveri Traders", "Bharat Hardware", "Northwind"].map((name) => ({ id: name, name })) };
    }
    if (url === "/trainer/templates/history") {
      const key = config?.params?.scope === "global" ? "global" : config?.params?.vendor_name ?? "";
      return { data: HISTORY[key] ?? [] };
    }
    throw new Error(`unexpected GET ${url}`);
  });
}

async function renderLoaded() {
  render(<RulesTable />);
  await screen.findAllByTestId("records-rule-group");
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  mockBackend();
});

describe("ruleGroupsFrom", () => {
  it("keeps Global first, vendors in the order given, and drops templates with no current rules", () => {
    const groups = ruleGroupsFrom(HISTORY.global, [
      { vendorName: "Rajesh Steel", history: HISTORY["Rajesh Steel"] },
      { vendorName: "Kaveri Traders", history: HISTORY["Kaveri Traders"] },
      { vendorName: "Northwind", history: [] },
      { vendorName: "Bharat Hardware", history: HISTORY["Bharat Hardware"] },
    ]);
    expect(groups.map((g) => [g.title, g.current.version, g.current.rules.length])).toEqual([
      ["Global", 2, 1],
      ["Rajesh Steel", 4, 2],
      ["Bharat Hardware", 1, 1],
    ]);
  });
});

describe("RulesTable (22.8)", () => {
  it("two vendor templates + Global render as three groups; empty and missing templates are absent", async () => {
    await renderLoaded();
    const groups = screen.getAllByTestId("records-rule-group");
    expect(groups.map((g) => within(g).getByRole("heading").textContent)).toEqual(["Global", "Rajesh Steel", "Bharat Hardware"]);
    expect(within(groups[1]).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Freight is not taxable.",
      "Due date is 45 days after invoice date.",
    ]);
    expect(screen.queryByText("Kaveri Traders")).toBeNull();
    expect(screen.queryByText("Northwind")).toBeNull();
  });

  it("links to the chat-rules page exactly once and never reads chat rules itself", async () => {
    await renderLoaded();
    expect(screen.getAllByRole("link").filter((a) => a.getAttribute("href") === "/settings/chat-rules")).toHaveLength(1);
    expect(api.get.mock.calls.map(([url]) => url)).not.toContain("/chat/rules");
  });

  it("History opens that group's versions, and rollback uses the Trainer's endpoint then reloads", async () => {
    api.post.mockResolvedValue({ data: { version: 5, reaudit_queued: true } });
    await renderLoaded();
    const rajesh = screen.getAllByTestId("records-rule-group")[1];
    fireEvent.click(within(rajesh).getByRole("button", { name: /History/ }));
    expect(await screen.findByText("Rule Version History & Rollback")).toBeInTheDocument();
    expect(screen.getByText("Vendor: Rajesh Steel")).toBeInTheDocument();

    const getsBefore = api.get.mock.calls.length;
    const rollbackButtons = screen.getAllByRole("button", { name: /Rollback/i });
    fireEvent.click(rollbackButtons[0]);
    const confirm = screen.queryAllByRole("button", { name: /Confirm/i });
    await act(async () => {
      if (confirm.length > 0) fireEvent.click(confirm[confirm.length - 1]);
    });
    expect(api.post).toHaveBeenCalledWith("/trainer/templates/tpl-r/rollback/3");
    expect(api.get.mock.calls.length).toBeGreaterThan(getsBefore);
  });

  it("an empty tenant sees an explanation, not a blank tab", async () => {
    api.get.mockImplementation(async (url: string) => ({ data: [] }));
    render(<RulesTable />);
    expect(await screen.findByText("No extraction rules yet")).toBeInTheDocument();
  });
});
