import { test, expect, Page } from "@playwright/test";

/**
 * E2E tests for Gap 277: Record INBOUND invoice as Paid from Invoices queue.
 */

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const MOCK_INVOICES = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    invoice_number: "INV-COMPLETED-101",
    vendor_name: "Acme Supplies",
    invoice_date: "2026-08-01",
    created_at: "2026-08-02",
    due_date: "2026-08-30",
    grand_total: 1500,
    currency: "USD",
    status: "COMPLETED",
    tags: ["office"],
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    invoice_number: "INV-PAID-202",
    vendor_name: "Beta Logistics",
    invoice_date: "2026-08-05",
    created_at: "2026-08-06",
    due_date: "2026-08-25",
    grand_total: 2400,
    currency: "USD",
    status: "PAID",
    tags: ["freight"],
  },
];

async function setupMocks(page: Page) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill(
      json({
        user_id: "user-1",
        tenant_id: "tenant-1",
        tenant_name: "Test Tenant",
        role: "Admin",
      })
    )
  );

  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
      })
    )
  );

  await page.route("**/api/invoices*", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "x-total-count": String(MOCK_INVOICES.length) },
      body: JSON.stringify(MOCK_INVOICES),
    });
  });
}

test.describe("Gap 277: Record Inbound Invoice as Paid", () => {
  test("shows 'Mark as Paid' in actions menu for COMPLETED invoice, but not for PAID invoice", async ({
    page,
  }) => {
    await setupMocks(page);
    await page.goto("/invoices");

    // Wait for the table rows to appear
    await expect(page.locator("text=INV-COMPLETED-101")).toBeVisible();
    await expect(page.locator("text=INV-PAID-202")).toBeVisible();

    // 1. Click actions menu on COMPLETED invoice (first row)
    const firstRowActions = page.locator("tr").filter({ hasText: "INV-COMPLETED-101" }).locator("button").first();
    await firstRowActions.click();

    // Verify "Mark as Paid" is visible
    const markPaidBtn = page.locator("button:has-text('Mark as Paid')");
    await expect(markPaidBtn).toBeVisible();

    // Close menu by clicking outside
    await page.locator("body").click();

    // 2. Click actions menu on PAID invoice (second row)
    const secondRowActions = page.locator("tr").filter({ hasText: "INV-PAID-202" }).locator("button").first();
    await secondRowActions.click();

    // Verify "Mark as Paid" is NOT visible for already PAID invoice
    await expect(page.locator("button:has-text('Mark as Paid')")).not.toBeVisible();
  });

  test("clicking 'Mark as Paid' triggers confirmation dialog and sends PUT /api/audit/resolve with PAID status", async ({
    page,
  }) => {
    await setupMocks(page);

    let resolveCalled = false;
    let resolvePayload: any = null;

    await page.route("**/api/audit/resolve/*", (route) => {
      resolveCalled = true;
      resolvePayload = route.request().postDataJSON();
      route.fulfill(json({ success: true }));
    });

    await page.goto("/invoices");
    await expect(page.locator("text=INV-COMPLETED-101")).toBeVisible();

    // Intercept and accept the confirmation dialog
    page.on("dialog", (dialog) => {
      expect(dialog.message()).toContain("Mark invoice INV-COMPLETED-101 as paid?");
      dialog.accept();
    });

    // Open actions menu and click "Mark as Paid"
    const rowActions = page.locator("tr").filter({ hasText: "INV-COMPLETED-101" }).locator("button").first();
    await rowActions.click();

    const markPaidBtn = page.locator("button:has-text('Mark as Paid')");
    await expect(markPaidBtn).toBeVisible();
    await markPaidBtn.click();

    // Verify API call was executed with status: "PAID"
    await expect.poll(() => resolveCalled).toBe(true);
    expect(resolvePayload).toEqual({
      status: "PAID",
      dismissed_alerts: [],
    });
  });
});
