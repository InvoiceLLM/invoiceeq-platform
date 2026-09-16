/**
 * FE Feature 22 Task 22.1 — PrimaryNav renders 3 items for an Auditor and 4 for
 * an Admin (spec §6), never flashes Settings while identity is loading, and
 * marks the surface the user is on.
 *
 * Asserted by name AND href, so an item that is renamed or re-pointed fails
 * rather than passing on a count alone.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { AuthContextType } from "@/hooks/useAuth";

const auth = vi.hoisted(() => ({ current: {} as Partial<AuthContextType> }));
const nav = vi.hoisted(() => ({ pathname: "/today" }));

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import PrimaryNav from "@/components/nav/PrimaryNav";

function links() {
  return within(screen.getByRole("complementary", { name: "Primary" }))
    .getAllByRole("link")
    .map((a) => [a.textContent, a.getAttribute("href")]);
}

beforeEach(() => {
  nav.pathname = "/today";
});

describe("PrimaryNav (22.1)", () => {
  it("renders the three universal surfaces for an Auditor", () => {
    auth.current = { role: "Auditor", canAudit: true, loading: false };
    render(<PrimaryNav />);
    expect(links()).toEqual([
      ["Today", "/today"],
      ["Ask", "/ask"],
      ["Records", "/records"],
    ]);
  });

  it("adds Settings for an Admin", () => {
    auth.current = { role: "Admin", canAudit: true, canTrain: true, canLoad: true, loading: false };
    render(<PrimaryNav />);
    expect(links()).toEqual([
      ["Today", "/today"],
      ["Ask", "/ask"],
      ["Records", "/records"],
      ["Settings", "/settings"],
    ]);
  });

  it("hides Settings while identity is still loading, and says so", () => {
    auth.current = { role: "", loading: true };
    render(<PrimaryNav />);
    expect(links().map(([name]) => name)).not.toContain("Settings");
    expect(screen.getByRole("complementary", { name: "Primary" })).toHaveAttribute("data-auth-loading", "true");
  });

  it("marks the current surface, including its sub-routes", () => {
    auth.current = { role: "Admin", loading: false };
    nav.pathname = "/settings/chat-rules";
    render(<PrimaryNav />);
    const current = screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page");
    expect(current.map((a) => a.textContent)).toEqual(["Settings"]);
  });
});
