import { test, expect } from "@playwright/test";

/**
 * Website Feature 7 / Gaps 345-350 -- Plug and Play Workflows homepage
 * surfaces. First committed Playwright coverage for these components; the
 * feature doc's own Verification Plan (section 6) recorded a scripted
 * headless-Chrome run instead of a spec, and this closes that gap.
 *
 * All four of HeroModeTabs, the Gap 346 SENTINEL discrepancy sample,
 * SageChatPreview and WorkflowRecipeSelector are fixture-driven and make zero
 * network calls (feature_7 spec section 7) -- these specs need the Next dev
 * server and nothing else, same as e2e/smoke.spec.ts.
 *
 * SandboxKeyCta is the one exception (section 7 amendment, Gap 350): it is
 * the only component that fetches, and only on click. Its default
 * (NEXT_PUBLIC_SANDBOX_KEYS_ENABLED unset) state is covered here, since that
 * is the shipped state of every environment today. The flag-on state needs a
 * differently-configured server (the value is baked in at build/dev-server
 * start) and lives in playwright.sandbox.config.ts /
 * e2e/sandbox-key-cta-enabled.spec.ts, following the precedent
 * playwright.proxy.config.ts already set for this exact problem.
 */

test.describe("HeroModeTabs (Gap 345) -- two-mode hero switcher", () => {
  test("defaults to the app tab, and switching tabs swaps the panel content", async ({ page }) => {
    await page.goto("/");

    const appTab = page.getByRole("tab", { name: "Complete Web Application" });
    const plugTab = page.getByRole("tab", { name: "Plug & Play Engine" });
    await expect(appTab).toHaveAttribute("aria-selected", "true");
    await expect(plugTab).toHaveAttribute("aria-selected", "false");

    const appPanel = page.locator("#hero-mode-panel-app");
    await expect(appPanel).toBeVisible();
    await expect(appPanel).toContainText("SENTINEL Review Console");
    await expect(appPanel).toContainText("Spend Analytics");
    await expect(appPanel).toContainText("Team Roles");
    await expect(page.locator("#hero-mode-panel-plug")).toHaveCount(0);

    await plugTab.click();
    await expect(plugTab).toHaveAttribute("aria-selected", "true");
    await expect(appTab).toHaveAttribute("aria-selected", "false");

    const plugPanel = page.locator("#hero-mode-panel-plug");
    await expect(plugPanel).toBeVisible();
    await expect(plugPanel).toContainText("Email In");
    await expect(plugPanel).toContainText("Drive Sync");
    await expect(plugPanel).toContainText("REST API");
    await expect(plugPanel).toContainText("Webhooks");
    // the inactive panel is unmounted, not hidden -- only one panel exists.
    await expect(page.locator("#hero-mode-panel-app")).toHaveCount(0);
  });

  test("the plug primitives link out to /signup with the matching intent", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: "Plug & Play Engine" }).click();

    await expect(page.getByRole("link", { name: /REST API/ })).toHaveAttribute(
      "href",
      "/signup?intent=api"
    );
    await expect(page.getByRole("link", { name: /Webhooks/ })).toHaveAttribute(
      "href",
      "/signup?intent=webhook"
    );
  });
});

test.describe("Pipeline demo -- Gap 346 SENTINEL discrepancy sample", () => {
  test("the clean default sample shows no warning card and an AUTOMATED status", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("Risk Score 99.8%")).toBeVisible();
    await expect(page.getByText("4. Verified Result")).toBeVisible();
    // Note: a plain substring match on "Held for Review" is not usable here --
    // SageChatPreview's second prompt chip contains the (lowercase) phrase
    // "still held for review?" elsewhere on the same page, and Playwright's
    // getByText is case-insensitive by default.
    await expect(page.getByText("4. Held for Review")).toHaveCount(0);
  });

  test("selecting the flagged FRT-1048 chip renders the discrepancy warning, the held-for-review stage label, and the flagged risk score", async ({
    page,
  }) => {
    await page.goto("/");

    const flaggedChip = page.getByRole("button", { name: "FRT-1048" });
    await expect(flaggedChip).toBeVisible();
    await flaggedChip.click();

    // The chip drives a 4-step, 600ms-interval animation before the warning
    // card (gated on activeStep >= 2) and stage 4's label settle -- poll
    // rather than asserting immediately after the click.
    await expect(page.getByText("Freight Surcharge came in at $5,200.00")).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByText("4. Held for Review")).toBeVisible();
    await expect(page.getByText("Routed to an auditor")).toBeVisible();
    await expect(page.getByText("Risk Score 61.2%")).toBeVisible();

    await expect(page.getByRole("heading", { name: "Global Freight Logistics" })).toBeVisible();
    await expect(page.getByText("AUDIT_REQUIRED", { exact: true }).first()).toBeVisible();
  });

  test("switching back to a clean sample makes the warning card disappear again", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("button", { name: "FRT-1048" }).click();
    await expect(page.getByText("4. Held for Review")).toBeVisible({ timeout: 5000 });

    await page.getByRole("button", { name: "INV-9842" }).click();
    await expect(page.getByText("4. Held for Review")).toHaveCount(0, { timeout: 5000 });
    await expect(page.getByText("Freight Surcharge came in at")).toHaveCount(0);
  });
});

test.describe("SageChatPreview (Gap 347) -- chip click reveals the canned answer", () => {
  test("no answer pane exists before a chip is clicked", async ({ page }) => {
    await page.goto("/#sage-preview");

    await expect(
      page.getByText("Pick a question above to see the answer SAGE returns")
    ).toBeVisible();
    await expect(page.getByText("Resolved query")).toHaveCount(0);
  });

  test("clicking a prompt chip reveals its answer, SQL and citations", async ({ page }) => {
    await page.goto("/#sage-preview");

    const chip = page.getByRole("button", { name: "Which invoices are still held for review?" });
    await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "true");

    await expect(page.getByText("3 are open. One price variance")).toBeVisible();
    await expect(page.getByText("Resolved query")).toBeVisible();
    await expect(page.locator("pre")).toContainText("HOLD_FOR_REVIEW");

    // "FRT-1048" alone is ambiguous -- it is also the sample-selector chip's
    // own label elsewhere on the page -- so scope to the citations row.
    const citationsRow = page.getByText("Grounded in").locator("..");
    for (const id of ["FRT-1048", "DUP-2201", "DUP-2202"]) {
      await expect(citationsRow).toContainText(id);
    }
  });

  test("clicking a second chip swaps the answer rather than appending it", async ({ page }) => {
    await page.goto("/#sage-preview");

    await page.getByRole("button", { name: "What did we spend on software last month?" }).click();
    await expect(page.getByText("$84,210.00 across 12 invoices")).toBeVisible();

    await page.getByRole("button", { name: "How did Q2 vendor costs compare to Q1?" }).click();
    await expect(page.getByText("Q2 came in at $312,400")).toBeVisible();
    await expect(page.getByText("$84,210.00 across 12 invoices")).toHaveCount(0);
  });
});

test.describe("WorkflowRecipeSelector (Gap 348) -- option selection updates the live summary", () => {
  test("defaults to the first option of every step and updates the sentence per click", async ({
    page,
  }) => {
    await page.goto("/#choose-your-workflow");

    const summary = page.getByText(/Your pipeline: invoices arrive via/);
    await expect(summary).toContainText("email in");
    await expect(summary).toContainText("auto-approved when clean");
    await expect(summary).toContainText("pushed to your webhook");
    await expect(summary).toContainText("with SAGE chat over the data");

    await page.getByRole("radio", { name: "Strict Human Review" }).click();
    await expect(summary).toContainText("reviewed by a human every time");
    await expect(summary).not.toContainText("auto-approved when clean");

    await page.getByRole("radio", { name: "Google Drive Folder" }).click();
    await expect(summary).toContainText("a watched Drive folder");

    await page.getByRole("radio", { name: "Pipeline Only" }).click();
    await expect(summary).toContainText("pipeline only, no chat");
    await expect(summary).not.toContainText("with SAGE chat over the data");
  });

  test("selecting an option marks it aria-checked and deselects its siblings in the same step", async ({
    page,
  }) => {
    await page.goto("/#choose-your-workflow");

    const auto = page.getByRole("radio", { name: "Full Auto-Pilot" });
    const flagged = page.getByRole("radio", { name: "Review Flagged Only" });
    await expect(auto).toHaveAttribute("aria-checked", "true");

    await flagged.click();
    await expect(flagged).toHaveAttribute("aria-checked", "true");
    await expect(auto).toHaveAttribute("aria-checked", "false");
  });
});

test.describe("SandboxKeyCta (Gap 350) -- default shipped state, flag unset", () => {
  test("renders exactly the Gap 348 Start Free Trial link, no sandbox button, no /api/ calls", async ({
    page,
  }) => {
    const apiCalls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/")) apiCalls.push(req.url());
    });

    await page.goto("/#choose-your-workflow");

    const cta = page.locator("#choose-your-workflow");
    await expect(cta.getByRole("link", { name: "Start Free Trial" })).toBeVisible();
    await expect(cta.getByRole("button", { name: "Get Sandbox API Key" })).toHaveCount(0);
    await expect(cta.getByRole("link", { name: "Start Free Trial" })).toHaveAttribute(
      "href",
      "/signup"
    );

    expect(apiCalls).toEqual([]);
  });
});
