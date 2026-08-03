import { test, expect } from "@playwright/test";

/**
 * `/billing/success` — Feature 3 / 3.1's return-flow page
 * (`app/billing/success/page.tsx`), shipped 2026-08-02 with zero prior
 * coverage (website_features_tracker.md Feature 3 note: "no committed test").
 *
 * The page is a pure server component that reads only `searchParams.plan`
 * and `searchParams.txnid` (no API call — see the big comment in the page
 * itself for why that's deliberate) and looks `plan` up in
 * `lib/billingPlans.ts::PLAN_COPY`. So the whole surface under test is that
 * lookup's three outcomes (known plan / unknown or missing plan / txnid
 * present-or-absent) plus the two outbound links, which read
 * `NEXT_PUBLIC_FE_URL` (pinned to `http://127.0.0.1:3399` by
 * playwright.config.ts specifically so this assertion is deterministic).
 */

const FE_ORIGIN = "http://127.0.0.1:3399";

test.describe("Billing success — known plan ids", () => {
  test("plan=pro renders the Pro name, price and blurb", async ({ page }) => {
    await page.goto("/billing/success?plan=pro&txnid=TXN-PRO-1");

    await expect(page.getByRole("heading", { name: /You're on\s*Pro/ })).toBeVisible();
    await expect(page.getByText("Plan", { exact: true })).toBeVisible();
    await expect(page.getByText("₹4,999 / month")).toBeVisible();
    await expect(
      page.getByText(/Unlimited invoices, full platform access, and up to 10 users/)
    ).toBeVisible();
  });

  test("plan=pro_combined renders the Pro Combined name, price and blurb", async ({ page }) => {
    await page.goto("/billing/success?plan=pro_combined&txnid=TXN-COMBINED-1");

    await expect(page.getByRole("heading", { name: /You're on\s*Pro Combined/ })).toBeVisible();
    await expect(page.getByText("₹8,999 / month")).toBeVisible();
    await expect(
      page.getByText(/Everything in Pro, plus the Sending flow/)
    ).toBeVisible();
  });
});

test.describe("Billing success — transaction reference", () => {
  test("txnid renders in its own dt/dd block, verbatim", async ({ page }) => {
    const txnid = "PAYU-REF-abc123XYZ";
    await page.goto(`/billing/success?plan=pro&txnid=${txnid}`);

    await expect(page.getByText("Transaction reference", { exact: true })).toBeVisible();
    await expect(page.getByText(txnid)).toBeVisible();
  });

  test("no txnid param -> no transaction reference block rendered", async ({ page }) => {
    await page.goto("/billing/success?plan=pro");

    await expect(page.getByText("Transaction reference", { exact: true })).toHaveCount(0);
  });
});

test.describe("Billing success — unknown or missing plan (fallback copy)", () => {
  test("no plan param at all -> generic heading, no Plan dt/dd block", async ({ page }) => {
    await page.goto("/billing/success");

    await expect(page.getByRole("heading", { name: "Your upgrade is live" })).toBeVisible();
    await expect(
      page.getByText("Your new plan is visible in Settings.")
    ).toBeVisible();
    // "Plan" dt only ever renders when `plan` resolved to a known PLAN_COPY entry.
    await expect(page.getByText("Plan", { exact: true })).toHaveCount(0);
  });

  test("plan param present but not in PLAN_COPY -> same fallback as no plan at all", async ({
    page,
  }) => {
    await page.goto("/billing/success?plan=enterprise_unlimited&txnid=TXN-X");

    await expect(page.getByRole("heading", { name: "Your upgrade is live" })).toBeVisible();
    await expect(page.getByText("Plan", { exact: true })).toHaveCount(0);
    // txnid is independent of plan resolution -- still shown.
    await expect(page.getByText("TXN-X")).toBeVisible();
  });
});

test.describe("Billing success — outbound links", () => {
  test("dashboard and settings links point at the FE origin's real paths", async ({ page }) => {
    await page.goto("/billing/success?plan=pro");

    const dashboardLink = page.getByRole("link", { name: "Go to your dashboard" });
    const settingsLink = page.getByRole("link", { name: "Review plan settings" });

    await expect(dashboardLink).toHaveAttribute("href", `${FE_ORIGIN}/dashboard`);
    await expect(settingsLink).toHaveAttribute("href", `${FE_ORIGIN}/settings`);
  });

  test("public by design -- no Clerk redirect, page renders with no session", async ({ page }) => {
    // No auth setup/cookies at all in this test -- the point being verified
    // is exactly that absence: the page must not bounce to a sign-in screen.
    const response = await page.goto("/billing/success?plan=pro");
    expect(response?.status()).toBe(200);
    await expect(page.getByText("Payment confirmed")).toBeVisible();
  });
});
