/**
 * FE Feature 22 Task 22.3 — Settings.
 *
 * Switch OFF: `/settings` is still the tile grid. Its snapshots were recorded
 * against the ORIGINAL app/settings/page.tsx before the grid moved into
 * components/settings/SettingsTileGrid.tsx, and were not re-recorded.
 *
 * Switch ON: one scrolling page. Each existing screen's page module is replaced
 * by a probe that — like the real pages — declares a header title and portals a
 * header action. That lets the tests prove three things at once: the section
 * mounts THAT module (not a re-implementation), the Settings title survives six
 * embedded pages each naming themselves, and their header actions render inline.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import React from "react";

const probe = vi.hoisted(() => (name: string) => {
  return async () => {
    const { usePageHeader, PageHeaderActions } = await import("@/components/layout/PageHeaderContext");
    return {
      default: function ProbePage() {
        usePageHeader({ title: `${name} page title` });
        return (
          <div data-testid={`page-${name}`}>
            <PageHeaderActions>
              <button type="button">{name} action</button>
            </PageHeaderActions>
          </div>
        );
      },
    };
  };
});

vi.mock("@/app/admin/page", probe("admin"));
vi.mock("@/app/settings/email/page", probe("email"));
vi.mock("@/app/settings/connectors/page", probe("connectors"));
vi.mock("@/app/settings/workflows/page", probe("workflows"));
vi.mock("@/app/settings/webhooks/page", probe("webhooks"));
vi.mock("@/app/settings/subscriptions/page", probe("subscriptions"));
vi.mock("@/app/settings/security/page", probe("security"));

const auth = vi.hoisted(() => ({ current: { role: "Admin", loading: false } as Record<string, unknown> }));

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/settings/ServiceFlowToggles", () => ({
  default: ({ role }: { role: string }) => <div data-testid="service-flow-toggles" data-role={role} />,
}));

import SettingsPage from "@/app/settings/page";
import {
  PageHeaderProvider,
  usePageHeaderActionsRef,
  usePageHeaderMeta,
} from "@/components/layout/PageHeaderContext";

function Header() {
  const meta = usePageHeaderMeta();
  return (
    <header data-testid="shell-header">
      <h1>{meta?.title ?? ""}</h1>
      <div data-testid="shell-header-actions" ref={usePageHeaderActionsRef()} />
    </header>
  );
}

function renderInShell() {
  return render(
    <PageHeaderProvider>
      <Header />
      <SettingsPage />
    </PageHeaderProvider>
  );
}

beforeEach(() => {
  auth.current = { role: "Admin", loading: false };
  window.history.replaceState(null, "", "/settings");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("/settings with the four surfaces OFF — the tile grid, unchanged", () => {
  it("Admin", () => {
    expect(render(<SettingsPage />).container.innerHTML).toMatchSnapshot();
  });

  it("non-Admin (admin-only tiles hidden)", () => {
    auth.current = { role: "Auditor", loading: false };
    expect(render(<SettingsPage />).container.innerHTML).toMatchSnapshot();
  });

  it("identity loading", () => {
    auth.current = { role: "", loading: true };
    expect(render(<SettingsPage />).container.innerHTML).toMatchSnapshot();
  });
});

describe("/settings with the four surfaces ON — one scrolling page (22.3)", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "true");
  });

  it("renders the six sections in order, each with its anchor", () => {
    renderInShell();
    const sections = Array.from(document.querySelectorAll("section[id]"));
    expect(sections.map((s) => s.id)).toEqual(["people", "inbox", "checks", "notify", "plan", "security"]);
    expect(sections.map((s) => s.querySelector("h2")?.textContent)).toEqual([
      "People",
      "Inbox",
      "Checks",
      "Notify",
      "Plan",
      "Security",
    ]);
    const jumpLinks = within(screen.getByRole("navigation", { name: "Settings sections" })).getAllByRole("link");
    expect(jumpLinks.map((a) => a.getAttribute("href"))).toEqual(sections.map((s) => `#${s.id}`));
  });

  it("mounts each existing screen's own page in its section", () => {
    renderInShell();
    const pagesIn = (id: string) =>
      Array.from(document.getElementById(id)!.querySelectorAll("[data-testid^='page-']")).map((el) =>
        el.getAttribute("data-testid")
      );
    expect({
      people: pagesIn("people"),
      inbox: pagesIn("inbox"),
      checks: pagesIn("checks"),
      notify: pagesIn("notify"),
      plan: pagesIn("plan"),
      security: pagesIn("security"),
    }).toEqual({
      people: ["page-admin"],
      inbox: ["page-email", "page-connectors"],
      checks: ["page-workflows"],
      notify: ["page-webhooks"],
      plan: ["page-subscriptions"],
      security: ["page-security"],
    });
    expect(within(document.getElementById("inbox")!).getByTestId("service-flow-toggles")).toHaveAttribute("data-role", "Admin");
  });

  it("keeps the Settings title and renders each embedded page's header actions in its own section", () => {
    renderInShell();
    expect(within(screen.getByTestId("shell-header")).getByRole("heading").textContent).toBe("Settings");
    expect(screen.getByTestId("shell-header-actions")).toBeEmptyDOMElement();
    expect(within(document.getElementById("notify")!).getByRole("button", { name: "webhooks action" })).toBeInTheDocument();
  });

  it("links to the chat-rules page exactly once, instead of embedding a second list", () => {
    renderInShell();
    const links = screen.getAllByRole("link").filter((a) => a.getAttribute("href") === "/settings/chat-rules");
    expect(links).toHaveLength(1);
    expect(document.getElementById("checks")!.contains(links[0])).toBe(true);
  });

  it("scrolls a deep link like #inbox to its section", () => {
    window.history.replaceState(null, "", "/settings#inbox");
    const scrolled: string[] = [];
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(function (this: Element) {
      scrolled.push(this.id);
    });
    renderInShell();
    expect(scrolled).toContain("inbox");
    expect(new Set(scrolled)).toEqual(new Set(["inbox"]));
  });
});
