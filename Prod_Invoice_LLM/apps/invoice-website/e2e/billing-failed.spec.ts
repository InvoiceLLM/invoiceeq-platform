import { test, expect } from "@playwright/test";

/**
 * `/billing/failed` — Feature 3 / 3.1's return-flow failure page
 * (`app/billing/failed/page.tsx`), shipped 2026-08-02 with zero prior
 * coverage. `resolveOutcome()` maps the backend's `?reason=` values (exactly
 * the ones `routers/billing.py::_handle_payu_callback` emits, per the page's
 * own comment) into one of three severities:
 *
 *   declined            -- reason=<absent>, txnid present (a plain decline);
 *                           or truly no params at all (UNKNOWN, still "declined")
 *   unconfirmed         -- reason=malformed | hash_mismatch | unverifiable
 *   charged_not_applied -- reason=unknown_plan | unknown_tenant
 *
 * `canRetry` is `severity === "declined"` only -- that's the one property
 * this suite most needs to nail down, since offering a retry CTA on a
 * possibly-already-charged outcome is the exact mistake the page's own
 * comment says must not happen.
 */

test.describe("Billing failed — declined severity (retry CTA present)", () => {
  test("txnid with no reason -> plain decline copy, retry CTA shown", async ({ page }) => {
    await page.goto("/billing/failed?txnid=TXN-DECLINED-1");

    await expect(page.getByText("Payment not completed", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Your payment didn't go through" })).toBeVisible();
    await expect(page.getByText(/you have not been charged/)).toBeVisible();

    await expect(page.getByRole("link", { name: "Try the checkout again" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Contact support" })).toHaveCount(0);
  });

  test("no params at all -> UNKNOWN fallback, still declined severity with retry CTA", async ({
    page,
  }) => {
    await page.goto("/billing/failed");

    await expect(page.getByRole("heading", { name: "Your payment wasn't completed" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Try the checkout again" })).toBeVisible();
    await expect(page.getByText("Transaction reference", { exact: true })).toHaveCount(0);
  });

  test("retry CTA links to the pricing anchor", async ({ page }) => {
    await page.goto("/billing/failed?txnid=TXN-DECLINED-2");
    await expect(page.getByRole("link", { name: "Try the checkout again" })).toHaveAttribute(
      "href",
      "/#pricing"
    );
  });
});

test.describe("Billing failed — unconfirmed severity (no retry CTA)", () => {
  const UNCONFIRMED_REASONS: { reason: string; heading: string }[] = [
    { reason: "malformed", heading: "We couldn't read the payment response" },
    { reason: "hash_mismatch", heading: "We couldn't confirm this payment was genuine" },
    { reason: "unverifiable", heading: "We couldn't reach PayU to confirm this payment" },
  ];

  for (const { reason, heading } of UNCONFIRMED_REASONS) {
    test(`reason=${reason} -> correct heading, badge, and no retry CTA`, async ({ page }) => {
      await page.goto(`/billing/failed?reason=${reason}&txnid=TXN-UNCONF-${reason}`);

      await expect(page.getByText("Payment could not be verified", { exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(page.getByText(/Your plan has not been changed/)).toBeVisible();

      // The one property that matters most: no "try again" CTA on an
      // unconfirmed outcome, per the page's own don't-invite-a-second-charge
      // comment.
      await expect(page.getByRole("link", { name: "Try the checkout again" })).toHaveCount(0);
    });
  }

  test("txnid still renders for an unconfirmed outcome", async ({ page }) => {
    await page.goto("/billing/failed?reason=hash_mismatch&txnid=TXN-UNCONF-REF");
    await expect(page.getByText("Transaction reference", { exact: true })).toBeVisible();
    await expect(page.getByText("TXN-UNCONF-REF")).toBeVisible();
  });
});

test.describe("Billing failed — charged_not_applied severity (no retry CTA, distinct messaging)", () => {
  const CHARGED_REASONS = ["unknown_plan", "unknown_tenant"];

  for (const reason of CHARGED_REASONS) {
    test(`reason=${reason} -> "charged but not applied" heading, red badge, no retry CTA`, async ({
      page,
    }) => {
      await page.goto(`/billing/failed?reason=${reason}&txnid=TXN-CHARGED-${reason}`);

      await expect(page.getByText("Charged — plan not applied", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "Your payment succeeded, but we couldn't apply it" })
      ).toBeVisible();
      await expect(page.getByText(/You have been charged and your workspace has not been upgraded/)).toBeVisible();

      await expect(page.getByRole("link", { name: "Try the checkout again" })).toHaveCount(0);
    });
  }

  test("unknown_plan and unknown_tenant render distinct detail copy from each other", async ({
    page,
  }) => {
    await page.goto("/billing/failed?reason=unknown_plan&txnid=TXN-A");
    await expect(
      page.getByText(/the plan it referenced isn't one we recognise/)
    ).toBeVisible();

    await page.goto("/billing/failed?reason=unknown_tenant&txnid=TXN-B");
    await expect(
      page.getByText(/we couldn't match it to a workspace/)
    ).toBeVisible();
  });
});

test.describe("Billing failed — support CTA fallback when NEXT_PUBLIC_SUPPORT_EMAIL is unset", () => {
  // playwright.config.ts's webServer deliberately does not set
  // NEXT_PUBLIC_SUPPORT_EMAIL, so `SUPPORT_EMAIL` is null here -- this is the
  // branch covered by this config; the mailto: branch is covered separately
  // by playwright.proxy.config.ts's billing-proxy-mode.spec.ts.
  test("charged_not_applied with no support email -> no mailto CTA, plain-text fallback shown", async ({
    page,
  }) => {
    await page.goto("/billing/failed?reason=unknown_plan&txnid=TXN-NOMAIL");

    await expect(page.getByRole("link", { name: "Contact support" })).toHaveCount(0);
    await expect(
      page.getByText(/Reach out through your usual support channel/)
    ).toBeVisible();
  });
});

test.describe("Billing failed — public by design", () => {
  test("renders with no session, no Clerk redirect", async ({ page }) => {
    const response = await page.goto("/billing/failed?txnid=TXN-PUBLIC");
    expect(response?.status()).toBe(200);
    await expect(page.getByText("Payment not completed", { exact: true })).toBeVisible();
  });

  test("dashboard link still offered regardless of severity", async ({ page }) => {
    await page.goto("/billing/failed?reason=unverifiable&txnid=TXN-X");
    await expect(page.getByRole("link", { name: "Back to your dashboard" })).toBeVisible();
  });
});
