import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 498: end-to-end check of the main money action — approving an inbound
 * invoice — on the review page where it lives. The queue-table "Mark as Paid"
 * menu this spec used to target was removed by FE Gap 318. Every /api/** call is
 * stubbed, so this needs the Next dev server but no backend.
 */

// The review page JIT-compiles on first request and embeds a PDF iframe.
test.describe.configure({ timeout: 120_000 });

const INVOICE_ID = "44444444-4444-4444-4444-444444444444";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const INVOICE = {
  id: INVOICE_ID,
  status: "AUDIT_REQUIRED",
  vendor_name: "Acme Supplies",
  invoice_number: "INV-1501",
  invoice_date: "2026-08-01",
  due_date: "2026-08-30",
  grand_total: 1500,
  tax_amount: 0,
  currency: "USD",
  flow_direction: "INBOUND",
  field_confidence: {},
  coordinates: [],
  items: [],
  sa_alerts: [],
};

async function stubReviewApis(page: Page, overrides: Record<string, unknown> = {}) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill(
      json({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        tenant_name: "E2E Workspace",
        user_id: "user_e2e_admin",
        role: "Admin",
        billing_plan: "active",
        can_train: true,
        can_audit: true,
        can_load: true,
      })
    )
  );
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
        outbound_sender_email: null,
        billing_plan: "free",
      })
    )
  );
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route("**/api/outbound-dashboard/invoices**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route(`**/api/invoices/${INVOICE_ID}/pdf`, (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
  );
  await page.route(`**/api/invoices/${INVOICE_ID}`, (route) =>
    route.fulfill(json({ ...INVOICE, ...overrides }))
  );
}

async function gotoReview(page: Page, overrides: Record<string, unknown> = {}) {
  await stubReviewApis(page, overrides);
  await page.goto(`/invoices/review/${INVOICE_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Auditor Review Console" })).toBeVisible({
    timeout: 90_000,
  });
}

test.describe("FE Gap 498: approve an inbound invoice from the review page", () => {
  test("Approve Invoice sends PUT /api/audit/resolve with status PAID", async ({ page }) => {
    let resolvePayload: Record<string, unknown> | null = null;
    await page.route(`**/api/audit/resolve/${INVOICE_ID}`, (route) => {
      resolvePayload = route.request().postDataJSON();
      route.fulfill(json({ success: true, already_resolved: false, corrections_applied: {} }));
    });

    await gotoReview(page);
    await page.locator("header").getByRole("button", { name: "Approve Invoice" }).click();

    await expect.poll(() => resolvePayload, { timeout: 20_000 }).not.toBeNull();
    expect(resolvePayload).toMatchObject({ status: "PAID", dismissed_alerts: [] });
  });

  test("an already-PAID invoice offers no Approve Invoice action", async ({ page }) => {
    await gotoReview(page, { status: "PAID" });

    await expect(page.locator("header").getByRole("button", { name: "Approve Invoice" })).toHaveCount(0);
  });
});
