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

    // Gap 163: logotype is now serif "Invoice" + an "AI" mono tag (was "Invoice.AI").
    await expect(page.getByRole("link", { name: "Invoice AI" })).toBeVisible();
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
    // Pre-warm the signup page to avoid compilation timeouts on slow local runs
    await page.goto("/signup");
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
  test("renders the sign-in form with credential fields", async ({ page }) => {
    const response = await page.goto("/login");
    expect(response?.status()).toBe(200);

    await expect(page.getByRole("heading", { name: "Welcome back", exact: true })).toBeVisible();
    await expect(page.getByPlaceholder("Work email")).toBeVisible();
    await expect(page.getByPlaceholder("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: /Sign In/ })).toBeVisible();
  });

  test("forgot-password and signup links are present", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password"
    );
    await expect(page.getByRole("link", { name: "Create an organisation →" })).toHaveAttribute(
      "href",
      "/signup"
    );
  });
});

test.describe("Marketing Header Visibility & Cross-Screen Navigation", () => {
  const routes = ["/", "/contact", "/login", "/signup", "/forgot-password"];

  for (const route of routes) {
    test(`renders the top navigation menu on ${route}`, async ({ page }) => {
      const response = await page.goto(route);
      expect(response?.status()).toBe(200);

      // Verify header brand logo/wordmark is visible
      await expect(page.getByRole("link", { name: "Invoice AI" })).toBeVisible();

      // Verify key navigation options in header
      const nav = page.getByRole("navigation");
      await expect(nav.getByRole("link", { name: "Contact Us" })).toBeVisible();
      if (route === "/login") {
        await expect(nav.getByRole("link", { name: "Register" })).toBeVisible();
      } else {
        await expect(nav.getByRole("link", { name: "Login" })).toBeVisible();
      }
    });
  }

  test("cross-screen anchor links target home page sections", async ({ page }) => {
    // Go to contact page first
    await page.goto("/contact");

    const nav = page.getByRole("navigation");
    
    // Check Features and Pricing link attributes pointing to home route hash
    await expect(nav.getByRole("link", { name: "Features" })).toHaveAttribute("href", "/#features");
    await expect(nav.getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/#pricing");
    await expect(nav.getByRole("link", { name: "Architecture Flow" })).toHaveAttribute("href", "/#architecture-flows");

    // Click Features and verify redirection to landing page with hash
    await nav.getByRole("link", { name: "Features" }).click();
    await expect(page).toHaveURL(/.*\/#features/);
  });
});

