import { test, expect, Page } from "@playwright/test";

/**
 * Feature 2.1 (Outbound Dashboard) verification plan:
 *   - a receive-only tenant sees an unchanged, undivided Dashboard
 *   - a both-enabled tenant sees the two-column metrics split
 *   - no combined/net figure appears in any branch
 *
 * Every backend call the page makes is stubbed here. The Service Flow toggles
 * are the thing under test, so faking them is the point rather than a
 * shortcut; the metric payloads are fixed so the assertions are about layout,
 * not about numbers the BE tests already cover
 * (invoice-be/tests/test_outbound_dashboard.py).
 */

const INBOUND_METRICS = {
  total_invoiced: 1750,
  paid_amount: 1000,
  outstanding_amount: 750,
  at_risk_amount: 500,
  average_processing_time: 12.5,
  extraction_accuracy: 96.4,
  active_alerts_count: 1,
  spend_over_time: [
    { date: "2026-06-20", amount: 1000 },
    { date: "2026-06-25", amount: 750 },
  ],
  top_vendors: [{ vendor_name: "Hardware Depot", amount: 1250 }],
  invoices_by_status: { PAID: 1, AUDIT_REQUIRED: 1 },
};

const OUTBOUND_METRICS = {
  total_invoiced_out: 2050,
  amount_collected: 1000,
  outstanding_receivables: 1050,
  at_risk_receivables: 300,
  average_days_to_payment: 10,
  verification_accuracy: 75,
  active_alerts_count: 1,
  revenue_over_time: [
    { date: "2026-06-20", amount: 1000 },
    { date: "2026-06-26", amount: 1050 },
  ],
  top_customers: [{ customer_name: "Vertex Industries", amount: 1250 }],
  invoices_by_status: { PAID: 1, SENT: 1 },
};

/** Text that would indicate a combined/net AP-vs-AR figure leaked onto the
 *  page. Both feature docs keep that comparison Chat-only. */
const FORBIDDEN_COMBINED_TEXT = [
  /net position/i,
  /net cash/i,
  /combined total/i,
  /net receivable/i,
];

async function stubDashboardApis(
  page: Page,
  flow: { receive_invoices_enabled: boolean; send_invoices_enabled: boolean }
) {
  // Feature 1.1: the shell resolves identity from GET /api/auth/me and
  // Sidebar.tsx filters nav on it. Pinned to Admin here so these Dashboard
  // layout assertions aren't sitting on top of whatever the fallback identity
  // happens to render when the backend isn't reachable.
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        user_id: "user_e2e_admin",
        role: "Admin",
        billing_plan: "active",
        can_train: true,
        can_audit: true,
        can_load: true,
      }),
    })
  );

  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...flow,
        outbound_sender_email: flow.send_invoices_enabled ? "billing@tenant.test" : null,
        billing_plan: flow.send_invoices_enabled ? "pro_combined" : "free",
      }),
    })
  );

  await page.route("**/api/dashboard/metrics**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(INBOUND_METRICS) })
  );

  await page.route("**/api/dashboard/outbound-metrics**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(OUTBOUND_METRICS) })
  );

  await page.route("**/api/dashboard/insights**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ insights: [] }) })
  );

  await page.route("**/api/dashboard/trainer-impact**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        rules_trained: { global: 0, vendor_specific: 0, total: 0 },
        vendors_needing_rules: [],
        audit_rate_trend: [],
      }),
    })
  );

  await page.route("**/api/invoices**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "x-total-count": "1" },
      body: JSON.stringify([
        {
          id: "11111111-1111-1111-1111-111111111111",
          invoice_number: "INV-IN-1",
          vendor_name: "Hardware Depot",
          grand_total: 500,
          status: "AUDIT_REQUIRED",
        },
      ]),
    })
  );

  await page.route("**/api/outbound-dashboard/invoices**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "x-total-count": "1" },
      body: JSON.stringify([
        {
          id: "22222222-2222-2222-2222-222222222222",
          invoice_number: "INV-OUT-1",
          customer_name: "Vertex Industries",
          grand_total: 900,
          status: "NEEDS_REVIEW",
          is_overdue: false,
        },
      ]),
    })
  );
}

const splitContainer = (page: Page) => page.getByTestId("dashboard-metrics-split");
const inboundTotalCard = (page: Page) => page.getByText("Total Invoiced", { exact: true });
const outboundTotalCard = (page: Page) => page.getByText("Total Invoiced Out", { exact: true });

/**
 * Panels are matched by heading role rather than free text: the trend panels'
 * loading placeholders ("Loading receivables trend analytics...") contain the
 * heading text as a substring, which makes a bare getByText ambiguous while
 * data is still in flight.
 */
const panel = (page: Page, name: string) => page.getByRole("heading", { name, exact: true });

test.describe("Dashboard — receive-only tenant", () => {
  test("renders the unchanged, undivided inbound Dashboard", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: false,
    });

    await page.goto("/dashboard");

    // Inbound overview is present and unchanged
    await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
    await expect(inboundTotalCard(page)).toBeVisible();
    await expect(panel(page, "Invoice Spend Trend")).toBeVisible();
    await expect(panel(page, "AI Score")).toHaveCount(1);

    // No split, and nothing outbound anywhere
    await expect(splitContainer(page)).toHaveCount(0);
    await expect(outboundTotalCard(page)).toHaveCount(0);
    await expect(panel(page, "Receivables Trend")).toHaveCount(0);
    await expect(page.getByText("Avg Days to Payment", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Sending" })).toHaveCount(0);
    await expect(panel(page, "Top Customers")).toHaveCount(0);
  });

  test("makes no outbound metrics request at all", async ({ page }) => {
    const outboundCalls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/dashboard/outbound-metrics")) outboundCalls.push(req.url());
    });

    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: false,
    });

    await page.goto("/dashboard");
    await expect(inboundTotalCard(page)).toBeVisible();
    // Give any stray effect a chance to fire before asserting the negative
    await page.waitForTimeout(500);

    expect(outboundCalls).toEqual([]);
  });
});

test.describe("Dashboard — both services enabled", () => {
  test("renders a two-column metrics split with both halves at once", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: true,
    });

    await page.goto("/dashboard");

    const split = splitContainer(page);
    await expect(split).toBeVisible();

    // Two labelled halves, both visible simultaneously -- no tab, no click
    await expect(page.getByRole("heading", { name: "Receiving" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sending" })).toBeVisible();
    await expect(inboundTotalCard(page)).toBeVisible();
    await expect(outboundTotalCard(page)).toBeVisible();

    // Each half's own distinctive panels
    await expect(panel(page, "Invoice Spend Trend")).toBeVisible();
    await expect(panel(page, "Receivables Trend")).toBeVisible();
    await expect(panel(page, "AI Score")).toHaveCount(2);
    await expect(page.getByText("Avg Days to Payment", { exact: true })).toBeVisible();

    // Side by side at desktop width, not stacked
    await page.setViewportSize({ width: 1600, height: 1000 });
    await expect(split).toHaveClass(/xl:grid-cols-2/);
  });

  test("shows no combined or net figure anywhere on the page", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: true,
    });

    await page.goto("/dashboard");
    await expect(outboundTotalCard(page)).toBeVisible();

    const body = page.locator("body");
    for (const pattern of FORBIDDEN_COMBINED_TEXT) {
      await expect(body).not.toHaveText(pattern);
    }

    // The two totals stay separate -- neither half shows their sum (3800)
    await expect(page.getByText("$3,800", { exact: false })).toHaveCount(0);
  });

  test("Needs Attention lists both directions, each linking to its own review screen", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: true,
    });

    await page.goto("/dashboard");

    await expect(panel(page, "Needs Attention")).toBeVisible();

    const inboundRow = page.getByRole("link", { name: /INV-IN-1/ });
    const outboundRow = page.getByRole("link", { name: /INV-OUT-1/ });

    await expect(inboundRow).toBeVisible();
    await expect(outboundRow).toBeVisible();

    await expect(inboundRow).toHaveAttribute(
      "href",
      "/invoices/review/11111111-1111-1111-1111-111111111111"
    );
    await expect(outboundRow).toHaveAttribute(
      "href",
      "/invoices/outbound-review/22222222-2222-2222-2222-222222222222"
    );
  });

  test("stacks the two halves instead of squeezing them on a narrow viewport", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: true,
      send_invoices_enabled: true,
    });

    await page.setViewportSize({ width: 720, height: 1200 });
    await page.goto("/dashboard");

    const split = splitContainer(page);
    await expect(split).toBeVisible();

    const inboundBox = await panel(page, "Invoice Spend Trend").boundingBox();
    const outboundBox = await panel(page, "Receivables Trend").boundingBox();

    expect(inboundBox).not.toBeNull();
    expect(outboundBox).not.toBeNull();
    // Stacked: the outbound half starts below the inbound half, not beside it
    expect(outboundBox!.y).toBeGreaterThan(inboundBox!.y);
  });
});

test.describe("Dashboard — send-only tenant", () => {
  test("renders only the outbound overview, with no empty inbound half", async ({ page }) => {
    await stubDashboardApis(page, {
      receive_invoices_enabled: false,
      send_invoices_enabled: true,
    });

    await page.goto("/dashboard");

    await expect(outboundTotalCard(page)).toBeVisible();
    await expect(panel(page, "Receivables Trend")).toBeVisible();
    await page.getByRole("button", { name: "Top Customers" }).click();
    await expect(panel(page, "Top Customers")).toBeVisible();

    // No split container, and no inbound remnants
    await expect(splitContainer(page)).toHaveCount(0);
    await expect(inboundTotalCard(page)).toHaveCount(0);
    await expect(panel(page, "Invoice Spend Trend")).toHaveCount(0);
    await expect(panel(page, "AI Score")).toHaveCount(1);
  });
});
