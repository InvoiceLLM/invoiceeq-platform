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
 *   Settings / Subscriptions -> Admin only
 */

const ALWAYS_VISIBLE = ["Dashboard", "Chat", "Help"];
const GRANTABLE = ["Ingest", "Audit Queue", "AI Trainer"];
// FE Gap 143 added "Subscriptions" (/settings/subscriptions) as a direct nav
// entry, gated on Admin exactly as Settings is.
const ADMIN_ONLY = ["Settings", "Subscriptions"];

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
        // BE Gap 133: the header/admin console now render the backend-resolved
        // tenant name instead of Clerk unsafeMetadata.orgName.
        tenant_name: "E2E Workspace",
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
        // FE Gap 183: per-currency array replaced the flat scalars. Empty here
        // -- an empty-tenant response really is [], not a fabricated USD zero
        // row -- which also exercises the grid's zero-state path.
        totals_by_currency: [],
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

  test("Ingest, Audit Queue, AI Trainer, Settings and Subscriptions are all absent", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");
    await expect(page.locator("aside")).toHaveAttribute("data-auth-loading", "false");

    for (const name of [...GRANTABLE, ...ADMIN_ONLY]) {
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
      // Settings and Subscriptions stay Admin-only regardless of granted
      // permissions.
      for (const name of ADMIN_ONLY) {
        await expect(navLink(page, name)).toHaveCount(0);
      }
    });
  }
});

test.describe("Sidebar — Admin", () => {
  test("sees every nav item, including Settings and Subscriptions", async ({ page }) => {
    // Admin implies all three permissions server-side
    // (dependencies.resolve_permissions), which is why the stub returns them.
    await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
    await page.goto("/dashboard");

    expect((await visibleNavItems(page)).sort()).toEqual(
      [...ALWAYS_VISIBLE, ...GRANTABLE, ...ADMIN_ONLY].sort()
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

/**
 * Gap 87 finding G gave the header's dead HelpCircle button a real href, and
 * this suite asserted that it navigated. Gap 110 then removed that icon
 * outright: it was a second entry point to the exact same /help route the
 * Sidebar already carries, and the shared header row now has the active page's
 * title and controls to fit as well.
 *
 * The requirement did not go away, it moved -- so neither did the test. It now
 * asserts both halves of that decision: exactly one Help entry point exists,
 * it is the Sidebar's, and it still reaches /help. Asserting only "the header
 * has no Help link" would pass just as well if /help became unreachable.
 */
test.describe("Help entry point (Gap 87 finding G, relocated by Gap 110)", () => {
  test("the Sidebar's Help item navigates to /help", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");

    await navLink(page, "Help").click();
    await expect(page).toHaveURL(/\/help$/);
  });

  test("the header no longer carries a duplicate Help link", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");
    await expect(page.locator("aside")).toHaveAttribute("data-auth-loading", "false");

    await expect(page.locator("header").getByRole("link", { name: /help/i })).toHaveCount(0);
    // ...and the one that remains is the Sidebar's, not zero overall.
    await expect(navLink(page, "Help")).toBeVisible();
  });
});

/**
 * FE Gap 110 — every screen's title now comes from one shared header rendered
 * by Shell, fed through PageHeaderContext by the active route. The regression
 * this guards is a page rendering its own second header bar underneath it,
 * which is what Trainer/Settings/the review consoles used to do (Gaps 76/88).
 */
test.describe("Shared page header (Gap 110)", () => {
  const ROUTES: { path: string; title: string }[] = [
    { path: "/dashboard", title: "Command Center" },
    { path: "/settings", title: "Settings" },
    { path: "/help", title: "Help Center" },
  ];

  for (const { path, title } of ROUTES) {
    test(`${path} renders exactly one header and one h1, titled "${title}"`, async ({ page }) => {
      await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
      await page.goto(path);

      const heading = page.getByRole("heading", { name: title, level: 1 });
      await expect(heading).toBeVisible();

      // One <header> element in the whole document: the shared one. Two would
      // mean a page had started drawing its own again.
      await expect(page.locator("header")).toHaveCount(1);
      await expect(page.locator("h1")).toHaveCount(1);
      // And that h1 is inside the shared header, not in the page body.
      await expect(page.locator("header h1")).toHaveText(title);
    });
  }

  test("Trainer's actions render in the shared header, not a second bar", async ({ page }) => {
    await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
    await page.route("**/api/trainer/vendors**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );
    // Feature 14: no session is opened on mount any more, and
    // POST /trainer/sessions/global is gone (410 on the backend, proxy route
    // deleted). The header actions this test is about render regardless of
    // whether a session is loaded, so an empty invoice list is enough.
    await page.route("**/api/invoices?**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await page.goto("/trainer");

    await expect(page.locator("header")).toHaveCount(1);
    await expect(page.locator("header h1")).toHaveText("AI Trainer");
    // Portalled up from app/trainer/page.tsx via <PageHeaderActions>.
    await expect(
      page.locator("header").getByRole("button", { name: /Review & Commit/ })
    ).toBeVisible();
    await expect(
      page.locator("header").getByRole("button", { name: /Rule History/ })
    ).toBeVisible();
  });

  test("the title updates on client-side navigation between routes", async ({ page }) => {
    await stubShell(page, { role: "Admin", can_train: true, can_audit: true, can_load: true });
    await page.goto("/dashboard");
    await expect(page.locator("header h1")).toHaveText("Command Center");

    // A stale title after a soft navigation is the specific failure mode a
    // context-fed header can have and a per-page header cannot.
    await navLink(page, "Help").click();
    await expect(page).toHaveURL(/\/help$/);
    await expect(page.locator("header h1")).toHaveText("Help Center");
  });
});

/**
 * Gaps 87 + 95. The search box was removed outright (dead element, no handler,
 * and the reporter's own "never going to be used"), and the bell — previously a
 * handler-less button with a permanently-lit dot implying notifications that
 * did not exist — became a real Needs Attention count linking to the queue.
 *
 * The count is asserted from the stub's `x-total-count` header rather than from
 * a row payload, because that header is what the component actually reads
 * (`limit=1`, so no page of rows is fetched just to count them).
 */
test.describe("Header — search box and notification bell (Gaps 87 + 95)", () => {
  test("no search box is rendered anywhere in the header", async ({ page }) => {
    await stubShell(page, { role: "Admin" });
    await page.goto("/dashboard");
    await expect(page.locator("aside")).toHaveAttribute("data-auth-loading", "false");

    await expect(page.locator("header").getByRole("textbox")).toHaveCount(0);
    await expect(page.getByPlaceholder(/search invoices/i)).toHaveCount(0);
  });

  test("bell is hidden from a user who cannot open the audit queue", async ({ page }) => {
    await stubShell(page, { role: "Viewer" });
    await page.goto("/dashboard");
    await expect(page.locator("aside")).toHaveAttribute("data-auth-loading", "false");

    await expect(page.locator("header").getByRole("link", { name: /need review|invoice queue/i })).toHaveCount(0);
  });

  test("bell shows no badge when nothing needs review", async ({ page }) => {
    // can_audit must be stubbed explicitly, not implied by role: useAuth() reads
    // the permission flags straight off /auth/me and never derives them from
    // "Admin" (the backend's resolve_permissions does that, and it is not in
    // play here). Without it the bell is correctly hidden and this test fails
    // for a reason unrelated to what it is checking -- which is how it stood
    // before Gap 110's pass, failing on master. Same fix in the test below.
    await stubShell(page, { role: "Admin", can_audit: true });
    await page.goto("/dashboard");

    const bell = page.locator("header").getByRole("link", { name: /invoice queue/i });
    await expect(bell).toBeVisible();
    // stubShell answers x-total-count: 0 -- an always-visible dot here is
    // exactly the old misleading behaviour this replaced.
    await expect(bell.locator("span")).toHaveCount(0);
  });

  test("bell shows the real count and links to the queue", async ({ page }) => {
    await stubShell(page, { role: "Admin", can_audit: true });
    // Registered after stubShell so this more specific route wins.
    await page.route("**/api/invoices?status=AUDIT_REQUIRED**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "x-total-count": "7" },
        body: "[]",
      })
    );
    await page.goto("/dashboard");

    const bell = page.locator("header").getByRole("link", { name: /7 invoices need review/i });
    await expect(bell).toBeVisible();
    await expect(bell.locator("span")).toHaveText("7");

    await bell.click();
    await expect(page).toHaveURL(/\/invoices$/);
  });
});
