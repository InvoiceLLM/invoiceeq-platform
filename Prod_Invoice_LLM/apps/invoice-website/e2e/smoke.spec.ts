import { test, expect } from "@playwright/test";

/**
 * Basic smoke coverage for the site's other real pages, added after the
 * billing pages (this suite's priority — see billing-*.spec.ts). Not
 * exhaustive interaction testing: landing/pricing/login all involve either
 * Clerk (`useUser()`/`useSignIn()`, needs a real Clerk instance reachable
 * over the network) or client-only animation components, so these specs
 * stick to "does it render its real content and structure", not full
 * checkout/sign-in flows -- those need dedicated, larger specs of their own
 * if this app's suite grows further.
 */

test.describe("Landing page", () => {
  test("renders the header, hero and pricing section without erroring", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);

    await expect(page.getByRole("link", { name: "Invoice.AI" })).toBeVisible();
    await expect(page.locator("#pricing")).toBeAttached();
  });

  test("nav links point at the expected targets", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("navigation").getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "href",
      "#pricing"
    );
    await expect(page.getByRole("navigation").getByRole("link", { name: "Login" })).toHaveAttribute(
      "href",
      "/login"
    );
  });

  test("Get Started Free CTA links to /login", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("link", { name: "Get Started Free" }).first()
    ).toHaveAttribute("href", "/login");
  });
});

test.describe("Pricing table (on the landing page)", () => {
  test("renders all three plan cards with their prices", async ({ page }) => {
    await page.goto("/");
    const pricing = page.locator("#pricing");

    await expect(pricing.getByText("Free", { exact: true })).toBeVisible();
    await expect(pricing.getByText("₹0", { exact: true })).toBeVisible();

    await expect(pricing.getByRole("heading", { name: "Pro", exact: true })).toBeVisible();
    await expect(pricing.getByText("₹4,999", { exact: true })).toBeVisible();

    await expect(pricing.getByRole("heading", { name: "Pro Combined" })).toBeVisible();
    await expect(pricing.getByText("₹8,999", { exact: true })).toBeVisible();
  });

  test("Free plan CTA navigates to /signup", async ({ page }) => {
    await page.goto("/");
    const pricing = page.locator("#pricing");
    const freeCta = pricing.getByRole("button", { name: "Get Started Free" });

    // Retried as a unit (Playwright's toPass), not a single click: found by
    // actually running this suite that a single click can be a silent no-op
    // here. SSR paints the button before React has finished hydrating and
    // attaching PricingTable's onClick handler, and Playwright's
    // actionability checks (visible/stable/receives-events) all pass against
    // that pre-hydration DOM -- so the click can land before there's any
    // handler listening for it. Retrying the click covers that window
    // without weakening what's being asserted (still a real click, still a
    // real navigation).
    await expect(async () => {
      await freeCta.click();
      await expect(page).toHaveURL(/\/signup$/, { timeout: 2000 });
    }).toPass({ timeout: 15000 });
  });
});

test.describe("Login page", () => {
  test("renders the sign-in form with role selector and credential fields", async ({ page }) => {
    const response = await page.goto("/login");
    expect(response?.status()).toBe(200);

    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    // ".first()" -- the role-toggle button and the submit button
    // ("-> Sign In as Admin") both contain the substring "Admin", which
    // would otherwise be a strict-mode violation.
    await expect(page.getByRole("button", { name: "Admin" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "User" }).first()).toBeVisible();
    await expect(page.getByPlaceholder("Work email")).toBeVisible();
    await expect(page.getByPlaceholder("Password")).toBeVisible();
  });

  test("role selector toggles which role is active", async ({ page }) => {
    await page.goto("/login");

    // Same ".first()" reasoning as above -- pins each locator to the
    // role-toggle button specifically, not whichever button currently
    // contains that substring.
    const adminBtn = page.getByRole("button", { name: "Admin" }).first();
    const userBtn = page.getByRole("button", { name: "User" }).first();

    await expect(page.getByRole("button", { name: /Sign In as Admin/ })).toBeVisible();
    await userBtn.click();
    await expect(page.getByRole("button", { name: /Sign In as User/ })).toBeVisible();
    await adminBtn.click();
    await expect(page.getByRole("button", { name: /Sign In as Admin/ })).toBeVisible();
  });

  test("forgot-password and signup links are present", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password"
    );
    await expect(page.getByRole("link", { name: /Create your organisation/ })).toHaveAttribute(
      "href",
      "/signup"
    );
  });
});
