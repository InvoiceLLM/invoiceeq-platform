/**
 * FE Feature 22 Task 22.1 — the Shell behind `NEXT_PUBLIC_FOUR_SURFACES`.
 *
 * OFF (the default) must be today's shell exactly: the Sidebar, the page, no
 * redirect — Tasks 22.2 / 22.4 / 22.6 have not built the surfaces yet. ON swaps
 * in PrimaryNav, sends an old route to its new home once, and never mounts the
 * old page while doing so (no flash, none of its API calls).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const nav = vi.hoisted(() => ({ pathname: "/chat", replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace }),
}));
vi.mock("@/components/layout/Sidebar", () => ({ default: () => <div data-testid="sidebar" /> }));
vi.mock("@/components/nav/PrimaryNav", () => ({ default: () => <div data-testid="primary-nav" /> }));
vi.mock("@/components/layout/Header", () => ({ default: () => null }));
vi.mock("@/components/settings/WorkflowSetupBanner", () => ({ default: () => null }));
vi.mock("@/components/layout/LayoutPreferenceContext", () => ({
  LayoutPreferenceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useLayoutPreference: () => ({ layout: "surfaces", saving: false, error: null, setLayout: vi.fn() }),
}));

import Shell from "@/components/layout/Shell";

function Page() {
  return <p>old page body</p>;
}

beforeEach(() => {
  nav.replace.mockReset();
  window.history.replaceState(null, "", "/chat?session=abc-123");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Shell — four surfaces OFF (default)", () => {
  it("is today's shell: Sidebar, the page, and no redirect", () => {
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "");
    nav.pathname = "/chat";
    render(
      <Shell>
        <Page />
      </Shell>
    );
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.queryByTestId("primary-nav")).toBeNull();
    expect(screen.getByText("old page body")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });
});

describe("Shell — four surfaces ON", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "true");
  });

  it("redirects an old route once, keeping its query, without mounting the old page", () => {
    nav.pathname = "/chat";
    render(
      <Shell>
        <Page />
      </Shell>
    );
    expect(screen.getByTestId("primary-nav")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar")).toBeNull();
    expect(screen.queryByText("old page body")).toBeNull();
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith("/ask?session=abc-123");
  });

  it("renders a route that stays put, with no redirect", () => {
    nav.pathname = "/settings/chat-rules";
    render(
      <Shell>
        <Page />
      </Shell>
    );
    expect(screen.getByText("old page body")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("leaves the standalone /flows demo without chrome or redirect (Gap 62)", () => {
    nav.pathname = "/flows";
    render(
      <Shell>
        <Page />
      </Shell>
    );
    expect(screen.queryByTestId("primary-nav")).toBeNull();
    expect(screen.getByText("old page body")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
