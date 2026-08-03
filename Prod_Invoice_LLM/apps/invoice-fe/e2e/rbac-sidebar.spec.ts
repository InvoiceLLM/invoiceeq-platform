import { test, expect, Page } from "@playwright/test";

/**
 * Feature 1.1 (Granular RBAC), Task 1.1.5 — Sidebar nav filtering.
 *
 * Before this, `hooks/useAuth.ts` was a localStorage mock that made everyone an
 * Admin and `Sidebar.tsx` rendered every item unconditionally (FE Gap 99), so
 * there was nothing role-dependent to assert. The sidebar now derives its items
 * from `GET /api/auth/me`, which is what these specs stub — each test pins a
 * specific identity and asserts the exact nav set that identity should see,
 * rather than loosening the assertion to "some items render".
 *
 * Access model under test (feature_1.1_rbac.md):
 *   Dashboard / Chat / Help  -> always
 *   Ingest                   -> can_load
 *   Audit Queue              -> can_audit
 *   AI Trainer               -> can_train
 *   Settings                 -> Admin only
 */

const ALWAYS_VISIBLE = ["Dashboard", "Chat", "Help"];
const GRANTABLE = ["Ingest", "Audit Queue", "AI Trainer"];

interface Identity {
  role: string;
  can_train?: boolean;
  can_audit?: boolean;
  can_load?: boolean;
}

/**
 * Stub identity plus every backend call /dashboard makes. The dashboard's own
 * content is not under test here — only which nav items the shell renders — so
 * the payloads are the minimum shape the page will accept without erroring.
 */
async function stubShell(page: Page, identity: Identity) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        user_id: "user_e2e",
        billing_plan: "active",
        can_train: false,
        can_audit: false,
        can_load: false,
        ...identity,
      }),
    })
  );

  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
        outbound_sender_email: null,
        billing_plan: "free",
      }),
    })
  );

  // Realistic-enough payloads: an empty `{}` makes the dashboard body throw
  // mid-render, which tears down the whole shell (Sidebar included) and would
  // make these assertions fail for a reason that has nothing to do with RBAC.
  await page.route("**/api/dashboard/metrics**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_invoiced: 0,
        paid_amount: 0,
        outstanding_amount: 0,
        at_risk_amount: 0,
        average_processing_time: 0,
        extraction_accuracy: 0,
        active_alerts_count: 0,
        spend_over_time: [],
        top_vendors: [],
        invoices_by_status: {},
      }),
    })
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
      headers: { "x-total-count": "0" },
      body: "[]",
    })
  );
}

const navLink = (page: Page, name: string) =>
  page.locator("aside").getByRole("link", { name, exact: true });

/**
 * The full set of nav item labels currently rendered in the sidebar.
 *
 * Waits on `data-auth-loading="false"` first: while identity is in flight the
 * sidebar shows only the 3 universal items, which is indistinguishable from a
 * permission-less user's final state. Asserting on Dashboard's visibility
 * alone is not enough -- Dashboard renders in both.
 */
async function visibleNavItems(page: Page): Promise<string[]> {
  const aside = page.locator("aside");
  await expect(aside).toHaveAttribute("data-auth-loading", "false");
  await expect(navLink(page, "Dashboard")).toBeVisible();
  return (await aside.getByRole("link").allInnerTexts()).map((t) => t.trim());
}

test.describe("Sidebar — permission-less user (the design's Viewer)", () => {
  test("sees only Dashboard, Chat and Help", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");

    expect((await visibleNavItems(page)).sort()).toEqual([...ALWAYS_VISIBLE].sort());
  });

  test("Ingest, Audit Queue, AI Trainer and Settings are all absent", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");
    await expect(page.locator("aside")).toHaveAttribute("data-auth-loading", "false");

    for (const name of [...GRANTABLE, "Settings"]) {
      await expect(navLink(page, name)).toHaveCount(0);
    }
  });
});

test.describe("Sidebar — individually granted permissions", () => {
  const cases: { granted: keyof Identity; label: string }[] = [
    { granted: "can_load", label: "Ingest" },
    { granted: "can_audit", label: "Audit Queue" },
    { granted: "can_train", label: "AI Trainer" },
  ];

  for (const { granted, label } of cases) {
    test(`${granted} reveals "${label}" and nothing else`, async ({ page }) => {
      await stubShell(page, { role: "Viewer", [granted]: true });
      await page.goto("/dashboard");

      expect((await visibleNavItems(page)).sort()).toEqual(
        [...ALWAYS_VISIBLE, label].sort()
      );
      // Settings stays Admin-only regardless of granted permissions.
      await expect(navLink(page, "Settings")).toHaveCount(0);
    });
  }
});

test.describe("Sidebar — Admin", () => {
  test("sees every nav item, including Settings", async ({ page }) => {
    // Admin implies all three permissions server-side
    // (dependencies.resolve_permissions), which is why the stub returns them.
    await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
    await page.goto("/dashboard");

    expect((await visibleNavItems(page)).sort()).toEqual(
      [...ALWAYS_VISIBLE, ...GRANTABLE, "Settings"].sort()
    );
  });

  test("renders the real tenant id in the footer, not the all-zeroes mock", async ({ page }) => {
    await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
    await page.goto("/dashboard");

    const aside = page.locator("aside");
    await expect(aside).toHaveAttribute("data-auth-loading", "false");
    await expect(aside).toContainText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    await expect(aside).not.toContainText("00000000-0000-0000-0000-000000000000");
  });
});

test.describe("Sidebar — identity lookup fails", () => {
  test("falls back to the three universal items, never to a full menu", async ({ page }) => {
    await page.route("**/api/auth/me", (route) => route.fulfill({ status: 401, body: "" }));
    await stubShell(page, { role: "Viewer" }); // registered after, so the 401 route wins for /auth/me
    await page.goto("/dashboard");

    expect((await visibleNavItems(page)).sort()).toEqual([...ALWAYS_VISIBLE].sort());
  });
});

test.describe("Header — Help button (Gap 87 finding G)", () => {
  test("navigates to /help instead of doing nothing", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");

    await page.getByRole("link", { name: "Help Center" }).click();
    await expect(page).toHaveURL(/\/help$/);
  });
});
