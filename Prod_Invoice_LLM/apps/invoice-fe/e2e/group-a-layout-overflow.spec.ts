import { test, expect, Page, Locator } from "@playwright/test";

/**
 * Group A (Layout / Viewport Overflow) verification — Gaps 86, 69, 85, 76.
 * Plan: docs/guides/fe_gap_plan_group_a_layout_overflow.md
 *
 * These are geometry assertions, not content assertions: each gap is "the
 * element is off-screen / on the wrong row / clipped", so every check measures
 * real rendered boxes via boundingBox() and compares them against the viewport
 * or against each other. Asserting visibility alone would pass on all four
 * gaps -- an element pushed below the fold is still "visible" to Playwright's
 * default definition, which is exactly why these regressions shipped.
 *
 * Every geometry read goes through expect.poll() rather than a single
 * measurement. Layout is not stable the instant a locator becomes visible:
 * under fullyParallel the Next dev server JIT-compiles each route on first
 * request, and webfont swap plus React hydration both shift boxes after paint.
 * A single measure()-then-assert passed solo and failed with 4 workers, which
 * is a flaky test rather than a real regression -- polling removes the race
 * without weakening what's being asserted.
 *
 * Every /api/** call is stubbed, same approach as
 * dashboard-outbound-split.spec.ts: needs the Next dev server, no FastAPI
 * backend, no DB, no seeded tenant.
 */

// The plan's stated baseline viewport for Gaps 69 and 76.
const BASELINE = { width: 1280, height: 720 };

// Generous because a cold dev-server route compile can take several seconds
// under parallel load; the assertion still fails fast once layout is stable.
const GEOMETRY_TIMEOUT = 20_000;

const SERVICE_FLOW_BOTH = {
  receive_invoices_enabled: true,
  send_invoices_enabled: true,
  outbound_sender_email: "billing@tenant.test",
  billing_plan: "pro_combined",
};

const SERVICE_FLOW_RECEIVE_ONLY = {
  receive_invoices_enabled: true,
  send_invoices_enabled: false,
  outbound_sender_email: null,
  billing_plan: "free",
};

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/**
 * Feature 1.1: the app shell now resolves identity from GET /api/auth/me
 * (hooks/useAuth.ts), and Sidebar.tsx filters its nav items on the result.
 * These specs exercise Ingestion / Trainer / Dashboard, which an Admin
 * reaches, so they pin an Admin identity rather than leaving the call to fail
 * against a backend that isn't running -- an unstubbed failure resolves to the
 * permission-less fallback, which would silently change what the shell renders
 * underneath these layout assertions.
 */
async function stubAuthMe(page: Page) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill(
      json({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        user_id: "user_e2e_admin",
        role: "Admin",
        billing_plan: "active",
        can_train: true,
        can_audit: true,
        can_load: true,
      })
    )
  );
}

async function stubIngestionApis(page: Page, flow: Record<string, unknown>) {
  await stubAuthMe(page);
  await page.route("**/api/settings/service-flow", (route) => route.fulfill(json(flow)));
  // Connector status drives ConnectorBrowseBar; empty = renders nothing, which
  // is the conservative case for an overflow test (fewer elements, so if the
  // column still overflows here it definitely overflows with connectors on).
  await page.route("**/api/connectors/status**", (route) => route.fulfill(json({})));
}

async function stubTrainerApis(page: Page) {
  await stubAuthMe(page);
  await page.route("**/api/trainer/vendors**", (route) =>
    route.fulfill(json([{ name: "Hardware Depot", invoice_count: 4 }]))
  );
  await page.route("**/api/trainer/sessions/global**", (route) =>
    route.fulfill(
      json({
        session_id: "sess-global-1",
        scope: "global",
        variables: [],
        chat_history: [],
      })
    )
  );
  await page.route("**/api/trainer/templates/history**", (route) => route.fulfill(json([])));
}

/**
 * Waits until layout has actually settled before anything is measured:
 * webfonts applied (they change text width, which drives the truncation and
 * row-sharing checks) and one animation frame past the anchor being visible.
 */
async function settle(page: Page, anchor: Locator) {
  await expect(anchor).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  );
}

/** Asserts a control is fully inside the viewport on both axes. */
async function expectFullyInViewport(
  locator: Locator,
  viewport: { width: number; height: number },
  name: string
) {
  await expect
    .poll(
      async () => {
        const box = await locator.boundingBox();
        if (!box) return "no bounding box";
        const problems: string[] = [];
        if (box.y < 0) problems.push(`top edge above viewport (y=${Math.round(box.y)})`);
        if (box.y + box.height > viewport.height)
          problems.push(
            `extends ${Math.round(box.y + box.height - viewport.height)}px below the fold`
          );
        if (box.x + box.width > viewport.width)
          problems.push(
            `extends ${Math.round(box.x + box.width - viewport.width)}px past the right edge`
          );
        if (box.x < 0) problems.push(`pushed off the left edge (x=${Math.round(box.x)})`);
        return problems.length === 0 ? "inside viewport" : problems.join("; ");
      },
      {
        timeout: GEOMETRY_TIMEOUT,
        message: `${name} should be fully inside the ${viewport.width}x${viewport.height} viewport`,
      }
    )
    .toBe("inside viewport");
}

// ---------------------------------------------------------------------------
// Gap 86 — Ingestion title + Receiving/Sending toggle share one row
// ---------------------------------------------------------------------------

test.describe("Gap 86 — Ingestion header row", () => {
  test("title and Receiving/Sending toggle occupy the same row", async ({ page }) => {
    await stubIngestionApis(page, SERVICE_FLOW_BOTH);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    const title = page.getByRole("heading", { name: "File Ingestion" });
    const receivingTab = page.getByRole("button", { name: "Receiving" });

    await settle(page, title);
    await expect(receivingTab).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // The actual regression: the toggle used to start below the title's box.
    // Vertical overlap == same row; and it must sit to the title's right.
    await expect
      .poll(
        async () => {
          const t = await title.boundingBox();
          const b = await receivingTab.boundingBox();
          if (!t || !b) return "missing box";
          const overlaps = t.y < b.y + b.height && b.y < t.y + t.height;
          if (!overlaps) {
            return `stacked: title y=${Math.round(t.y)}..${Math.round(
              t.y + t.height
            )}, toggle y=${Math.round(b.y)}..${Math.round(b.y + b.height)}`;
          }
          if (b.x <= t.x) return "toggle is not to the right of the title";
          return "same row";
        },
        {
          timeout: GEOMETRY_TIMEOUT,
          message: "title and Receiving/Sending toggle should share one row",
        }
      )
      .toBe("same row");
  });

  test("toggle is absent for a receive-only tenant (unchanged behavior)", async ({ page }) => {
    await stubIngestionApis(page, SERVICE_FLOW_RECEIVE_ONLY);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    await settle(page, page.getByRole("heading", { name: "File Ingestion" }));
    // showTabs is false -- moving the toggle into PageHeader must not make it
    // appear for a single-service tenant.
    await expect(page.getByRole("button", { name: "Receiving" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sending" })).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Gap 69 — Ingestion left column fits the viewport
// ---------------------------------------------------------------------------

test.describe("Gap 69 — Ingestion left column overflow", () => {
  test("Bulk Directory Scan is fully within the viewport at 1280x720", async ({ page }) => {
    await stubIngestionApis(page, SERVICE_FLOW_RECEIVE_ONLY);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    await settle(page, page.getByRole("heading", { name: "File Ingestion" }));

    // The whole control -- not just its top edge -- must be above the fold.
    // This is the assertion that fails on the pre-fix layout (it ended 146px
    // below the fold at this viewport).
    await expectFullyInViewport(
      page.getByRole("button", { name: /Bulk Directory Scan/ }),
      BASELINE,
      "Bulk Directory Scan"
    );
  });

  test("the Submit button is also above the fold", async ({ page }) => {
    await stubIngestionApis(page, SERVICE_FLOW_RECEIVE_ONLY);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    await settle(page, page.getByRole("heading", { name: "File Ingestion" }));
    await expectFullyInViewport(
      page.getByRole("button", { name: /Submit Ingestion Batch/ }),
      BASELINE,
      "Submit Ingestion Batch"
    );
  });

  test("scan form is collapsed by default and expands on click, input still works", async ({
    page,
  }) => {
    await stubIngestionApis(page, SERVICE_FLOW_RECEIVE_ONLY);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    await settle(page, page.getByRole("heading", { name: "File Ingestion" }));

    const scanToggle = page.getByRole("button", { name: /Bulk Directory Scan/ });
    const pathInput = page.getByPlaceholder("/path/to/watched/folder");

    // Collapsed by default
    await expect(scanToggle).toHaveAttribute("aria-expanded", "false");
    await expect(pathInput).toHaveCount(0);

    await scanToggle.click();

    await expect(scanToggle).toHaveAttribute("aria-expanded", "true");
    await expect(pathInput).toBeVisible();

    // The form still functions exactly as before the disclosure was added:
    // typing enables Scan Directory, which posts to the watcher endpoint.
    let watcherCalled = false;
    await page.route("**/api/invoices/watcher**", (route) => {
      watcherCalled = true;
      return route.fulfill(
        json({ batch_id: "b1", job_ids: [], files_found: 0, files_queued: 0 })
      );
    });

    const scanButton = page.getByRole("button", { name: "Scan Directory" });
    await expect(scanButton).toBeDisabled();
    await pathInput.fill("/srv/dropbox");
    await expect(scanButton).toBeEnabled();
    await scanButton.click();

    await expect.poll(() => watcherCalled, { timeout: GEOMETRY_TIMEOUT }).toBe(true);
  });

  test("Sending tab's left column also fits the viewport", async ({ page }) => {
    await stubIngestionApis(page, SERVICE_FLOW_BOTH);
    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion");

    await settle(page, page.getByRole("heading", { name: "File Ingestion" }));
    await page.getByRole("button", { name: "Sending" }).click();

    const uploadButton = page.getByRole("button", { name: /Upload & Extract/ });
    await expect(uploadButton).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    await expectFullyInViewport(uploadButton, BASELINE, "Upload & Extract");
  });
});

// ---------------------------------------------------------------------------
// Gap 85 — Dashboard title vs. filter row (reproduction attempt)
// ---------------------------------------------------------------------------

/**
 * Gap 85 was reported live but never reproduced at a known viewport size, and
 * the plan explicitly says not to guess a fix before reproducing it. These
 * tests therefore assert the property that would be violated *if* the
 * reported crowding were real -- the title staying legible and the filter
 * controls staying on-screen -- across a sweep of widths, so the gap can be
 * either reproduced at a specific width or ruled out with evidence.
 *
 * Outcome as of 2026-07-31: not reproduced at any width below. Kept as
 * regression cover so a future change that does crowd the row fails loudly.
 */
test.describe("Gap 85 — Dashboard header row across widths", () => {
  async function stubDashboard(page: Page) {
    await stubAuthMe(page);
    await page.route("**/api/settings/service-flow", (route) =>
      route.fulfill(json(SERVICE_FLOW_RECEIVE_ONLY))
    );
    await page.route("**/api/dashboard/metrics**", (route) =>
      route.fulfill(
        json({
          total_invoiced: 1750,
          paid_amount: 1000,
          outstanding_amount: 750,
          at_risk_amount: 500,
          average_processing_time: 12.5,
          extraction_accuracy: 96.4,
          active_alerts_count: 1,
          spend_over_time: [],
          top_vendors: [],
          invoices_by_status: {},
        })
      )
    );
    await page.route("**/api/dashboard/insights**", (route) =>
      route.fulfill(json({ insights: [] }))
    );
    await page.route("**/api/dashboard/trainer-impact**", (route) =>
      route.fulfill(
        json({
          rules_trained: { global: 0, vendor_specific: 0, total: 0 },
          vendors_needing_rules: [],
          audit_rate_trend: [],
        })
      )
    );
    await page.route("**/api/invoices**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route("**/api/outbound-dashboard/invoices**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
  }

  for (const width of [1024, 1152, 1280, 1440, 1600]) {
    test(`title stays legible and filters stay on-screen at ${width}px`, async ({ page }) => {
      await stubDashboard(page);
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/dashboard");

      const title = page.getByRole("heading", { name: "Command Center" });
      await settle(page, title);

      // "Crowded" in a truncating flex row means the title has been squeezed
      // below its natural width and is showing an ellipsis. Compare rendered
      // width against the text's own scrollWidth to detect that directly.
      await expect
        .poll(
          async () => title.evaluate((el) => el.scrollWidth > el.clientWidth + 1),
          {
            timeout: GEOMETRY_TIMEOUT,
            message: `Dashboard title should not be truncated at ${width}px (truncation here == Gap 85 reproduced)`,
          }
        )
        .toBe(false);

      // Every filter control must be fully inside the viewport horizontally.
      const selects = page.locator("select");
      await expect.poll(() => selects.count(), { timeout: GEOMETRY_TIMEOUT }).toBeGreaterThan(0);

      const count = await selects.count();
      for (let i = 0; i < count; i++) {
        await expectFullyInViewport(
          selects.nth(i),
          { width, height: 900 },
          `filter control ${i} at ${width}px`
        );
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Gap 76 — Trainer Commit button visible, page frame doesn't scroll
// ---------------------------------------------------------------------------

test.describe("Gap 76 — Trainer header clipping", () => {
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    test(`Commit and Rule History are fully visible at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      await stubTrainerApis(page);
      await page.setViewportSize(viewport);
      await page.goto("/trainer");

      const commit = page.getByRole("button", { name: /Commit to Template Registry/ });
      const history = page.getByRole("button", { name: /Rule History/ });

      await settle(page, commit);

      // Fully inside the viewport on both axes -- the pre-fix h-screen bug
      // pushed content past the bottom edge (boundingBox().y went negative
      // once Shell's <main> scrolled), and a non-shrinking title could push
      // these past the right edge.
      await expectFullyInViewport(commit, viewport, "Commit to Template Registry");
      await expectFullyInViewport(history, viewport, "Rule History");
    });
  }

  /**
   * This is the assertion that actually reproduces the reported symptom.
   *
   * At scrollTop=0 the Commit button is on screen even on the pre-fix code, so
   * a plain "is it visible" check passes on the bug and proves nothing. The
   * real defect is that the page was ~178px taller than its container, which
   * makes Shell's <main> scrollable on a screen designed not to scroll -- so
   * any scroll at all (mouse wheel over the page frame, keyboard, or a browser
   * restoring a previous scroll position) carries the header's Commit button
   * off the top. That is the "clipped/not visible" the tester hit.
   */
  test("Commit stays on screen after scrolling the page frame to the bottom", async ({ page }) => {
    await stubTrainerApis(page);
    await page.setViewportSize(BASELINE);
    await page.goto("/trainer");

    const commit = page.getByRole("button", { name: /Commit to Template Registry/ });
    await settle(page, commit);

    // Try to scroll the app frame as far as it will go.
    await page.evaluate(() => {
      const main = document.querySelector("main");
      if (main) main.scrollTop = main.scrollHeight;
    });
    await page.evaluate(
      () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    );

    // Post-fix there is nothing to scroll, so the button cannot move.
    await expectFullyInViewport(commit, BASELINE, "Commit to Template Registry after scroll");
  });

  test("the page frame itself does not scroll -- only the inner panels do", async ({ page }) => {
    await stubTrainerApis(page);
    await page.setViewportSize(BASELINE);
    await page.goto("/trainer");

    await settle(page, page.getByRole("button", { name: /Commit to Template Registry/ }));

    // Shell's <main> is the scroll container for every in-app route. With
    // h-screen the Trainer overflowed it by ~178px; with h-full it must fit,
    // leaving no outer scrollbar. 2px tolerance for sub-pixel border rounding.
    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const main = document.querySelector("main");
            if (!main) return null;
            return main.scrollHeight - main.clientHeight;
          }),
        {
          timeout: GEOMETRY_TIMEOUT,
          message:
            "Shell <main> should not be scrollable on /trainer -- a positive value means the page is taller than its container",
        }
      )
      .toBeLessThanOrEqual(2);
  });
});
