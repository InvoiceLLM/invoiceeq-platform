import { test, expect } from "@playwright/test";

/**
 * Runs ONLY under playwright.sandbox.config.ts
 * (`npx playwright test --config=playwright.sandbox.config.ts`), a second dev
 * server with NEXT_PUBLIC_SANDBOX_KEYS_ENABLED=true and BACKEND_API_URL
 * pointed at e2e/sandbox-backend-stub.mjs -- the one server-only-env-baked
 * branch the main config's pass cannot exercise (see that config file's own
 * comment). MUST NOT run in the same pass as the main suite -- enforced by
 * playwright.config.ts's testIgnore not matching this file's name pattern
 * plus this config's own testMatch, same mechanism
 * billing-proxy-mode.spec.ts uses.
 *
 * The default (flag-unset) rendering is covered in
 * e2e/plug-and-play-homepage.spec.ts's "SandboxKeyCta (Gap 350)" block --
 * this file only covers what that pass structurally cannot reach.
 */

test.describe("SandboxKeyCta (Gap 350) -- flag on, real relay, stubbed backend", () => {
  test("issuing a key calls the relay, reveals the key once, and keeps Start Free Trial as a secondary link", async ({
    page,
  }) => {
    const apiCalls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/sandbox/keys")) apiCalls.push(req.url());
    });

    await page.goto("/#choose-your-workflow");
    const cta = page.locator("#choose-your-workflow");

    const issueButton = cta.getByRole("button", { name: "Get Sandbox API Key" });
    await expect(issueButton).toBeVisible();
    // no fetch before the click -- section 7's amendment: click-only, never on load.
    expect(apiCalls).toEqual([]);

    // Start Free Trial survives as a secondary link even while the sandbox
    // button is available, per SandboxKeyCta's own contract.
    await expect(cta.getByRole("link", { name: "Start Free Trial" })).toBeVisible();

    await issueButton.click();

    await expect(cta.getByText("Sandbox key issued")).toBeVisible();
    const revealed = cta.getByTestId("sandbox-key-value");
    await expect(revealed).toHaveText(/^inv_test_/);

    // The real limits from the stubbed backend response, not hardcoded copy.
    await expect(cta).toContainText("5 invoices, 25 chat messages");
    await expect(cta).toContainText("read and upload only");
    await expect(cta.getByRole("link", { name: "Keep this workspace — sign up" })).toHaveAttribute(
      "href",
      "/signup"
    );

    expect(apiCalls).toHaveLength(1);
    expect(apiCalls[0]).toContain("/api/sandbox/keys");
  });

  test("the issued key is persisted to localStorage under the documented key", async ({ page }) => {
    await page.goto("/#choose-your-workflow");
    await page.locator("#choose-your-workflow").getByRole("button", { name: "Get Sandbox API Key" }).click();
    await expect(page.getByTestId("sandbox-key-value")).toBeVisible();

    const stored = await page.evaluate(() =>
      window.localStorage.getItem("invoiceeq.sandbox_key.v1")
    );
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored as string);
    expect(parsed.apiKey).toMatch(/^inv_test_/);
    expect(parsed.tenantId).toBe("e2e00000-0000-0000-0000-000000000001");
  });

  test("reloading the page restores the key from localStorage without a second issuance call", async ({
    page,
  }) => {
    const apiCalls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/sandbox/keys")) apiCalls.push(req.url());
    });

    await page.goto("/#choose-your-workflow");
    await page.locator("#choose-your-workflow").getByRole("button", { name: "Get Sandbox API Key" }).click();
    await expect(page.getByTestId("sandbox-key-value")).toBeVisible();
    expect(apiCalls).toHaveLength(1);

    await page.reload();
    await expect(page.getByText("Your sandbox key")).toBeVisible();
    await expect(page.getByTestId("sandbox-key-value")).toHaveText(/^inv_test_/);
    // Restored from localStorage -- no second POST.
    expect(apiCalls).toHaveLength(1);
  });
});
