/**
 * FE Feature 22 Task 22.1 — the old-route map and the shared active-link rule.
 *
 * The route test runs over the map itself (every row must land on a surface
 * URL) AND over the routes that must NOT move at this level — a map that grew
 * a prefix match would silently redirect the outbound review page or the
 * chat-rules screen (FE Gap 478), and only the second half catches that.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LEGACY_ROUTE_REDIRECTS,
  activeNavHref,
  fourSurfacesEnabled,
  legacyRedirectFor,
} from "@/lib/navigation";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("legacyRedirectFor (22.1)", () => {
  it.each(LEGACY_ROUTE_REDIRECTS.filter((r) => !r.from.includes(":")).map((r) => [r.from, r.to]))("%s -> %s", (from, to) => {
    expect(legacyRedirectFor(from)).toBe(to);
  });

  it("every row lands on a /today, /ask, /records?tab= or /settings# URL", () => {
    for (const row of LEGACY_ROUTE_REDIRECTS) {
      expect(row.to).toMatch(/^(\/today|\/ask|\/ask\?invoice=:id|\/records\?tab=[a-z]+|\/settings#[a-z-]+)$/);
    }
  });

  it.each([
    "/invoices/review",
    "/invoices/review/",
    "/invoices/review/4b1e/extra",
    "/invoices/outbound-review/4b1e",
    "/ingestion",
    "/settings/chat-rules",
    "/settings/connectors",
    "/settings",
    "/flows",
    "/chat/something",
    "/today",
    "/ask",
    "/records",
  ])("%s stays put at this level", (pathname) => {
    expect(legacyRedirectFor(pathname)).toBeNull();
  });

  it("carries the incoming query string over", () => {
    expect(legacyRedirectFor("/chat", "?session=abc-123")).toBe("/ask?session=abc-123");
  });

  it("sends the builder page to the Records drawer, keeping the source (22.2)", () => {
    expect(legacyRedirectFor("/invoices/outbound-builder", "?source=11111111")).toBe(
      "/records?tab=out&source=11111111"
    );
  });

  it("sends each Settings sub-route to its section anchor (22.3)", () => {
    expect(
      Object.fromEntries(
        ["/admin", "/settings/email", "/settings/workflows", "/settings/webhooks", "/settings/subscriptions", "/settings/security"].map(
          (from) => [from, legacyRedirectFor(from)]
        )
      )
    ).toEqual({
      "/admin": "/settings#people",
      "/settings/email": "/settings#inbox",
      "/settings/workflows": "/settings#checks",
      "/settings/webhooks": "/settings#notify",
      "/settings/subscriptions": "/settings#plan",
      "/settings/security": "/settings#security",
    });
  });

  it("sends the review page to Ask with that invoice, one segment only (22.12)", () => {
    expect(legacyRedirectFor("/invoices/review/4b1e-99")).toBe("/ask?invoice=4b1e-99");
    // The target's own key wins over a carried-over one.
    expect(legacyRedirectFor("/invoices/review/4b1e", "?invoice=other&from=bell")).toBe("/ask?invoice=4b1e&from=bell");
  });

  it("sends the Trainer to Ask, exact match only (22.13)", () => {
    expect(legacyRedirectFor("/trainer")).toBe("/ask");
    expect(legacyRedirectFor("/trainer/history")).toBeNull();
  });

  it("sends the retired dashboard to Today (22.9)", () => {
    expect(legacyRedirectFor("/dashboard")).toBe("/today");
  });

  it("keeps the hash last when a query is carried over", () => {
    expect(legacyRedirectFor("/settings/subscriptions", "?upgraded=1")).toBe("/settings?upgraded=1#plan");
  });

  it("lets the target's own keys win over the old URL's", () => {
    expect(legacyRedirectFor("/invoices", "?tab=out&status=OPEN")).toBe("/records?tab=in&status=OPEN");
  });
});

describe("activeNavHref (shared by Sidebar and PrimaryNav)", () => {
  const items = [{ href: "/settings" }, { href: "/settings/subscriptions" }, { href: "/records" }];

  it("prefers the most specific match (FE Gap 143)", () => {
    expect(activeNavHref(items, "/settings/subscriptions")).toBe("/settings/subscriptions");
    expect(activeNavHref(items, "/settings/security")).toBe("/settings");
  });

  it("does not treat a shared string prefix as a path prefix", () => {
    expect(activeNavHref([{ href: "/record" }], "/records")).toBeUndefined();
  });
});

describe("fourSurfacesEnabled", () => {
  it("is off unless explicitly 'true'", () => {
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "");
    expect(fourSurfacesEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "1");
    expect(fourSurfacesEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_FOUR_SURFACES", "true");
    expect(fourSurfacesEnabled()).toBe(true);
  });
});
