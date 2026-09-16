/**
 * FE Feature 22 Task 22.13 — teach mode + TeachCard.
 *
 * Spec §6: typing "teach: freight is not taxable for Rajesh" yields a TeachCard
 * with scope defaulted to Rajesh; Confirm posts to the EXISTING
 * `POST /trainer/sessions/{id}/commit`. Plus: a teach message is never sent to
 * the chat; Propose goes from-invoice -> chat -> preview and writes nothing;
 * Confirm carries the preview token; "All vendors" is not offered as a working
 * choice (the backend removed it); no permission -> no calls.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
const auth = vi.hoisted(() => ({ canTrain: true }));
vi.mock("@/lib/apiClient", () => ({ apiClient: api }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ canTrain: auth.canTrain, loading: false, role: "Admin" }) }));

import TeachCard from "@/components/chat/cards/TeachCard";
import ChatWindow from "@/components/chat/ChatWindow";
import { defaultVendorFor, parseTeachCommand } from "@/lib/teach";
import type { VendorOption } from "@/lib/trainer-service";

function vendor(name: string, sampleInvoiceId = `inv-${name}`): VendorOption {
  return { id: name, name, invoiceCount: 3, sampleInvoiceId, sampleFileName: "x.pdf", samplePdfUrl: "" };
}
const VENDORS = [vendor("Kaveri Logistics"), vendor("Rajesh Traders", "inv-rajesh"), vendor("Rajdhani Steel")];

function backend({ newRule = "Freight lines are not taxable." as string | null } = {}) {
  api.get.mockImplementation(async (url: string) => {
    if (url === "/trainer/vendors") return { data: VENDORS };
    throw new Error(`unexpected GET ${url}`);
  });
  api.post.mockImplementation(async (url: string) => {
    if (url === "/trainer/sessions/from-invoice") return { data: { sessionId: "tsess-1", scope: "existing_vendor", vendorName: "Rajesh Traders" } };
    if (url === "/trainer/sessions/tsess-1/chat")
      return { data: { updatedSession: { sessionId: "tsess-1", scope: "existing_vendor", vendorName: "Rajesh Traders" }, newRuleCreated: newRule } };
    if (url === "/trainer/sessions/tsess-1/preview")
      return { data: { previewToken: "tok-9", scope: "existing_vendor", vendorName: "Rajesh Traders", newRules: [], impact: { summary: "Would change 2 of 14 past invoices." } } };
    if (url === "/trainer/sessions/tsess-1/commit")
      return { data: { status: "success", scope: "existing_vendor", vendor_name: "Rajesh Traders", version: 4, rules: { constraints: [] }, reaudit_queued: true } };
    throw new Error(`unexpected POST ${url}`);
  });
}

async function click(name: string) {
  const button = await screen.findByRole("button", { name });
  await act(async () => {
    fireEvent.click(button);
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  auth.canTrain = true;
});

describe("parseTeachCommand / defaultVendorFor (22.13)", () => {
  it("recognises the teach prefix only at the start, any case", () => {
    expect(parseTeachCommand("teach: freight is not taxable for Rajesh")).toBe("freight is not taxable for Rajesh");
    expect(parseTeachCommand("  TEACH :  round totals ")).toBe("round totals");
    expect(parseTeachCommand("teach:")).toBeNull();
    expect(parseTeachCommand("please teach: x")).toBeNull();
    expect(parseTeachCommand("what did you teach")).toBeNull();
  });

  it("defaults to the one vendor the sentence names, and to nobody when it is ambiguous", () => {
    expect(defaultVendorFor("freight is not taxable for Rajesh", VENDORS)?.name).toBe("Rajesh Traders");
    expect(defaultVendorFor("kaveri logistics rounds totals", VENDORS)?.name).toBe("Kaveri Logistics");
    expect(defaultVendorFor("freight is not taxable", VENDORS)).toBeNull();
    // "Raj" is a prefix of both, and not a whole first word of either.
    expect(defaultVendorFor("for Raj", VENDORS)).toBeNull();
    expect(defaultVendorFor("for Rajesh", [...VENDORS, vendor("Rajesh Paper")])).toBeNull();
  });
});

describe("teach mode in the composer (22.13)", () => {
  it("a teach: message raises the card and is never sent as chat", async () => {
    const onSend = vi.fn();
    const onTeach = vi.fn();
    render(
      <ChatWindow
        sessions={[]}
        activeSessionId="s1"
        messages={[]}
        isLoadingSessions={false}
        isLoadingMessages={false}
        isSending={false}
        error={null}
        onCreateSession={vi.fn()}
        onSelectSession={vi.fn()}
        onSendMessage={onSend}
        onRenameSession={vi.fn()}
        onDeleteSession={vi.fn()}
        onTeach={onTeach}
      />
    );
    const textarea = document.getElementById("chat-input-textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).toContain("teach:");
    fireEvent.change(textarea, { target: { value: "teach: freight is not taxable for Rajesh" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onTeach).toHaveBeenCalledWith("freight is not taxable for Rajesh");
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "total spend this month" } });
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("total spend this month");
    expect(onTeach).toHaveBeenCalledTimes(1);
  });
});

describe("TeachCard (22.13)", () => {
  it("defaults the scope to Rajesh and offers All vendors only as a disabled choice", async () => {
    backend();
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    const scope = (await screen.findByLabelText(/Applies to/)) as HTMLSelectElement;
    expect(scope.value).toBe("Rajesh Traders");
    const all = within(scope).getByRole("option", { name: /All vendors/ }) as HTMLOptionElement;
    expect(all.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("Propose opens a session on that vendor's invoice, asks the Trainer, previews — and commits nothing", async () => {
    backend();
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    await screen.findByLabelText(/Applies to/);
    await click("Propose rule");
    expect(api.post.mock.calls).toEqual([
      ["/trainer/sessions/from-invoice", { invoice_id: "inv-rajesh", session_mode: "rule_creation" }],
      ["/trainer/sessions/tsess-1/chat", { content: "freight is not taxable for Rajesh" }],
      ["/trainer/sessions/tsess-1/preview"],
    ]);
    expect(screen.getByTestId("teach-card-rule")).toHaveTextContent("Freight lines are not taxable.");
    expect(screen.getByText("Would change 2 of 14 past invoices.")).toBeInTheDocument();
  });

  it("Confirm posts to the existing commit endpoint with the preview token, once", async () => {
    backend();
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    await screen.findByLabelText(/Applies to/);
    await click("Propose rule");
    await click("Confirm");
    const commits = api.post.mock.calls.filter(([url]) => String(url).endsWith("/commit"));
    expect(commits).toEqual([["/trainer/sessions/tsess-1/commit", { preview_token: "tok-9" }]]);
    expect(screen.getByTestId("teach-card-committed")).toHaveTextContent("Saved for Rajesh Traders (version 4)");
  });

  it("when the Trainer proposes no rule there is nothing to confirm", async () => {
    backend({ newRule: null });
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    await screen.findByLabelText(/Applies to/);
    await click("Propose rule");
    expect(screen.getByTestId("teach-card-no-rule")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(api.post.mock.calls.map(([url]) => url)).not.toContain("/trainer/sessions/tsess-1/preview");
  });

  it("no vendor named -> no default, and Propose waits for a choice", async () => {
    backend();
    render(<TeachCard ruleText="round every total to the rupee" />);
    const scope = (await screen.findByLabelText(/Applies to/)) as HTMLSelectElement;
    expect(scope.value).toBe("");
    expect(screen.getByRole("button", { name: "Propose rule" })).toBeDisabled();
  });

  it("shows the server's reason when a step is refused", async () => {
    backend();
    api.post.mockRejectedValueOnce({ response: { data: { detail: "Upgrade to Pro to use the Trainer." } } });
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    await screen.findByLabelText(/Applies to/);
    await click("Propose rule");
    expect(screen.getByRole("alert")).toHaveTextContent("Upgrade to Pro to use the Trainer.");
    expect(screen.getByRole("button", { name: "Propose rule" })).toBeEnabled();
  });

  it("without can_train it explains, and calls nothing", async () => {
    auth.canTrain = false;
    backend();
    render(<TeachCard ruleText="freight is not taxable for Rajesh" />);
    expect(screen.getByTestId("teach-card-no-permission")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
