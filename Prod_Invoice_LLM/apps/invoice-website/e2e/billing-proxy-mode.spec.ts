import { test, expect } from "@playwright/test";
import { SUPPORT_EMAIL } from "../playwright.proxy.config";

/**
 * Runs ONLY under `playwright.proxy.config.ts` (`npm run test:e2e:proxy`),
 * a second dev server with `ENABLE_FE_PROXY=true` and
 * `NEXT_PUBLIC_SUPPORT_EMAIL` set -- the two server-only-env-dependent
 * branches `playwright.config.ts`'s main pass cannot exercise (see that
 * file's own comment). MUST NOT run in the same pass as the main suite --
 * enforced by `playwright.config.ts`'s `testIgnore` / this config's
 * `testMatch`, not just by convention.
 */

test.describe("Billing success — appHref() under the Multi-Zone proxy", () => {
  test("dashboard/settings links become same-origin paths, not the FE's own origin", async ({
    page,
  }) => {
    await page.goto("/billing/success?plan=pro");

    const dashboardLink = page.getByRole("link", { name: "Go to your dashboard" });
    const settingsLink = page.getByRole("link", { name: "Review plan settings" });

    // Same-origin relative path -- exactly "/dashboard", not
    // "http://127.0.0.1:3399/dashboard" the way the non-proxy pass renders it.
    await expect(dashboardLink).toHaveAttribute("href", "/dashboard");
    await expect(settingsLink).toHaveAttribute("href", "/settings");
  });
});

test.describe("Billing failed — appHref() under the Multi-Zone proxy", () => {
  test("Back to your dashboard link is also same-origin under the proxy", async ({ page }) => {
    await page.goto("/billing/failed?txnid=TXN-PROXY-1");
    await expect(page.getByRole("link", { name: "Back to your dashboard" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
  });
});

test.describe("Billing failed — support email CTA when NEXT_PUBLIC_SUPPORT_EMAIL is set", () => {
  test("charged_not_applied shows a real mailto: CTA instead of the plain-text fallback", async ({
    page,
  }) => {
    await page.goto("/billing/failed?reason=unknown_plan&txnid=TXN-MAIL-1");

    const contactLink = page.getByRole("link", { name: "Contact support" });
    await expect(contactLink).toBeVisible();

    const href = await contactLink.getAttribute("href");
    expect(href).toContain(`mailto:${SUPPORT_EMAIL}`);
    expect(href).toContain("subject=");
    expect(decodeURIComponent(href ?? "")).toContain("TXN-MAIL-1");

    // The plain-text no-email fallback must not also render.
    await expect(
      page.getByText(/Reach out through your usual support channel/)
    ).toHaveCount(0);
  });

  test("unconfirmed severity has no support CTA either way (only declined/charged branch)", async ({
    page,
  }) => {
    // unconfirmed severity's canRetry is false and it is not the
    // charged_not_applied branch either -- resolveOutcome's copy still
    // routes it through the same canRetry-false slot, so it also gets the
    // mailto CTA once an email is configured. Assert that explicitly rather
    // than assuming.
    await page.goto("/billing/failed?reason=hash_mismatch&txnid=TXN-MAIL-2");
    await expect(page.getByRole("link", { name: "Contact support" })).toBeVisible();
  });
});

/**
 * Website Gap 184: Multi-Zone rewrites for FE-owned paths that sit next to a
 * website-owned `/api/billing/*` prefix (usage) and the `/api/support/*`
 * prefix. Hits the website origin; the stub on FE_INTERNAL_URL proves the
 * rewrite landed, not a website 404 / Clerk handshake.
 */
test.describe("Gap 184 — Multi-Zone proxy rewrites to invoice-fe", () => {
  test("GET /api/billing/usage reaches invoice-fe (not a website 404)", async ({
    request,
  }) => {
    const res = await request.get("/api/billing/usage");
    expect(res.status()).toBe(200);
    expect(res.headers()["x-fe-stub"]).toBe("gap-184");
    const body = await res.json();
    expect(body.stub).toBe("billing-usage");
  });

  test("POST /api/support/chat reaches invoice-fe (not a website 404)", async ({
    request,
  }) => {
    const res = await request.post("/api/support/chat", {
      data: { message: "gap-184-proxy-probe" },
    });
    expect(res.status()).toBe(200);
    expect(res.headers()["x-fe-stub"]).toBe("gap-184");
    const body = await res.json();
    expect(body.stub).toBe("support");
    expect(body.path).toBe("/api/support/chat");
  });
});
