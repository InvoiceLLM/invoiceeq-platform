import { test, expect, Page } from "@playwright/test";

/**
 * FE Feature 17 / FE Gap 323 + 325 -- the Plug and Play Setup Wizard at
 * /settings/workflows, backed by BE Feature 25's GET/PUT
 * /api/v1/settings/workflow (proxied through app/api/settings/workflow/route.ts).
 *
 * Every /api/** call is stubbed (same convention as e2e/gaps-282-284-286.spec.ts
 * and e2e/rbac-sidebar.spec.ts) -- this needs the Next dev server but no FastAPI
 * backend, DB or seeded tenant. The wizard's own logic (step navigation,
 * multi-select vs single-select semantics, the disabled option that must not
 * be forceable, the save round-trip and its failure path, and the Quick Start
 * panel) is what is under test here, not the backend's validation rules.
 *
 * Current state, verified by reading app/settings/workflows/page.tsx before
 * writing this spec (not assumed from the feature doc): drive_archive is the
 * ONLY option still rendered disabled ("Not available yet -- BE Gap 338").
 * Both email_summary (BE Gap 339) and the widget chat-access option (BE Gap
 * 341 / FE Gap 325) are live and selectable.
 */

const json = (body: unknown, extra: Partial<{ status: number }> = {}) => ({
  status: extra.status ?? 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const ADMIN_ME = {
  tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  tenant_name: "E2E Workspace",
  user_id: "user_e2e_admin",
  role: "Admin",
  billing_plan: "active",
  can_train: true,
  can_audit: true,
  can_load: true,
};

const RESTRICTED_ME = {
  tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  tenant_name: "E2E Workspace",
  user_id: "user_e2e_restricted",
  role: "Restricted",
  billing_plan: "active",
  can_train: false,
  can_audit: false,
  can_load: false,
};

const EMPTY_CONFIG = {
  input_channels: [],
  audit_policy: "strict_review",
  output_destinations: [],
  chat_access: "dashboard",
  completed_at: null,
  api_key_scope: "readonly",
};

/**
 * Catch-all first (Playwright gives precedence to the most-recently-registered
 * handler), then the specific routes this page and the Shell it renders inside
 * actually call.
 */
async function stubShell(
  page: Page,
  opts: {
    identity?: Record<string, unknown>;
    workflowGet?: unknown;
    widgetTokens?: unknown[];
  } = {}
) {
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/auth/me", (route) => route.fulfill(json(opts.identity ?? ADMIN_ME)));
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({ receive_invoices_enabled: true, send_invoices_enabled: false, outbound_sender_email: null, billing_plan: "free" })
    )
  );
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route("**/api/settings/security/widget-tokens", (route) => {
    if (route.request().method() !== "GET") return route.fulfill(json({}));
    return route.fulfill(json(opts.widgetTokens ?? []));
  });
  if (opts.workflowGet !== undefined) {
    await page.route("**/api/settings/workflow", (route) => {
      if (route.request().method() !== "GET") return route.continue();
      return route.fulfill(json(opts.workflowGet));
    });
  }
}

const option = (page: Page, value: string) => page.getByTestId("workflow-option-" + value);

test.describe("Setup Wizard -- access gate", () => {
  test("a non-Admin sees Access Restricted and the workflow endpoint is never called", async ({ page }) => {
    let workflowCalls = 0;
    await stubShell(page, { identity: RESTRICTED_ME });
    await page.route("**/api/settings/workflow", (route) => {
      workflowCalls += 1;
      return route.fulfill(json(EMPTY_CONFIG));
    });

    await page.goto("/settings/workflows", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Access Restricted" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Return to Settings" })).toHaveAttribute("href", "/settings");
    expect(workflowCalls).toBe(0);
  });
});

test.describe("Setup Wizard -- step navigation and selection semantics", () => {
  test.beforeEach(async ({ page }) => {
    await stubShell(page, { workflowGet: EMPTY_CONFIG });
    await page.goto("/settings/workflows", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Where do invoices come in?" })).toBeVisible();
  });

  test("step 1 is multi-select: independent toggles via role=checkbox", async ({ page }) => {
    for (const value of ["email", "drive", "api", "manual"]) {
      await expect(option(page, value)).toHaveAttribute("role", "checkbox");
      await expect(option(page, value)).toHaveAttribute("aria-checked", "false");
    }

    await option(page, "email").click();
    await option(page, "api").click();
    await expect(option(page, "email")).toHaveAttribute("aria-checked", "true");
    await expect(option(page, "api")).toHaveAttribute("aria-checked", "true");
    await expect(option(page, "drive")).toHaveAttribute("aria-checked", "false");

    await option(page, "email").click();
    await expect(option(page, "email")).toHaveAttribute("aria-checked", "false");
    await expect(option(page, "api")).toHaveAttribute("aria-checked", "true");
  });

  test("step 2 is single-select: picking one deselects the other and shows the resulting scope", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "How much can a machine finish on its own?" })).toBeVisible();

    await expect(option(page, "full_automation")).toHaveAttribute("role", "radio");
    await option(page, "full_automation").click();
    await expect(option(page, "full_automation")).toHaveAttribute("aria-checked", "true");
    await expect(option(page, "strict_review")).toHaveAttribute("aria-checked", "false");
    await expect(page.getByText("Resulting API key scope:")).toBeVisible();
    await expect(page.getByText("actions", { exact: true })).toBeVisible();

    await option(page, "strict_review").click();
    await expect(option(page, "strict_review")).toHaveAttribute("aria-checked", "true");
    await expect(option(page, "full_automation")).toHaveAttribute("aria-checked", "false");
    await expect(page.getByText("readonly", { exact: true })).toBeVisible();
  });

  test("step 3: drive_archive is disabled and cannot be force-selected; email_summary and webhook can", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Where should results go?" })).toBeVisible();

    const drive = option(page, "drive_archive");
    await expect(drive).toHaveAttribute("aria-disabled", "true");
    await expect(drive).toContainText("Not available yet");
    await drive.click({ force: true });
    await expect(drive).toHaveAttribute("aria-checked", "false");

    const emailSummary = option(page, "email_summary");
    await expect(emailSummary).toHaveAttribute("aria-disabled", "false");
    await expect(emailSummary).not.toContainText("Not available yet");
    await emailSummary.click();
    await expect(emailSummary).toHaveAttribute("aria-checked", "true");

    await option(page, "webhook").click();
    await expect(option(page, "webhook")).toHaveAttribute("aria-checked", "true");
    await expect(emailSummary).toHaveAttribute("aria-checked", "true");
  });

  test("step 4: the widget option is live (no pill, selectable) and shows the missing-token hint at zero tokens", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "How will you use chat?" })).toBeVisible();

    const widget = option(page, "widget");
    await expect(widget).toHaveAttribute("aria-disabled", "false");
    await expect(widget).not.toContainText("Not available yet");

    await widget.click();
    await expect(widget).toHaveAttribute("aria-checked", "true");
    await expect(option(page, "dashboard")).toHaveAttribute("aria-checked", "false");
    await expect(page.getByTestId("widget-token-missing-hint")).toBeVisible();
  });

  test("step 4: the missing-token hint does not render once a token exists", async ({ page }) => {
    await page.route("**/api/settings/security/widget-tokens", (route) =>
      route.fulfill(
        json([
          {
            id: "t1",
            label: "Marketing site",
            token_prefix: "inv_widget_abc123",
            masked_token: "inv_widget_abc123...",
            allowed_origins: [],
            created_at: "2026-08-30T00:00:00Z",
            last_used_at: null,
          },
        ])
      )
    );
    await page.goto("/settings/workflows", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Where do invoices come in?" })).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByRole("button", { name: "Next" }).click();

    await option(page, "widget").click();
    await expect(page.getByTestId("widget-token-missing-hint")).toHaveCount(0);
  });

  test("the Review step lists every answer and the tablist can jump directly to any step", async ({
    page,
  }) => {
    await option(page, "email").click();
    await option(page, "api").click();
    await page.getByRole("tab", { name: "Audit policy" }).click();
    await option(page, "full_automation").click();
    await page.getByRole("tab", { name: "Review" }).click();

    await expect(page.getByRole("heading", { name: "Review and activate" })).toBeVisible();
    const review = page.locator("dl");
    await expect(review).toContainText("Email, Direct API");
    await expect(review).toContainText("Full Automation");
    await expect(review).toContainText("actions");
  });
});

test.describe("Setup Wizard -- save", () => {
  test("Save & Activate PUTs the draft, shows the success banner, and renders the Quick Start panel for an API-based answer", async ({
    page,
  }) => {
    await stubShell(page, { workflowGet: EMPTY_CONFIG });
    let putBody: Record<string, unknown> | null = null;
    const saved = {
      input_channels: ["email", "api"],
      audit_policy: "full_automation",
      output_destinations: ["webhook"],
      chat_access: "api",
      completed_at: "2026-08-30T05:39:40.226121",
      api_key_scope: "actions",
    };
    await page.route("**/api/settings/workflow", (route) => {
      if (route.request().method() === "GET") return route.fulfill(json(EMPTY_CONFIG));
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON();
        return route.fulfill(json(saved));
      }
      return route.fulfill(json({}));
    });

    await page.goto("/settings/workflows", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Where do invoices come in?" })).toBeVisible();

    await option(page, "email").click();
    await option(page, "api").click();
    await page.getByRole("button", { name: "Next" }).click();
    await option(page, "full_automation").click();
    await page.getByRole("button", { name: "Next" }).click();
    await option(page, "webhook").click();
    await page.getByRole("button", { name: "Next" }).click();
    await option(page, "api").click();
    await page.getByRole("button", { name: "Review" }).click();

    await page.getByTestId("workflow-save").click();

    await expect(page.getByTestId("workflow-saved")).toBeVisible();
    await expect(page.getByTestId("workflow-saved")).toContainText("actions");

    expect(putBody).toEqual({
      input_channels: ["email", "api"],
      audit_policy: "full_automation",
      output_destinations: ["webhook"],
      chat_access: "api",
    });

    await expect(page.getByText("Quick start")).toBeVisible();
    await expect(page.getByText("Upload an invoice")).toBeVisible();
    await expect(page.getByText("Ask SAGE a question")).toBeVisible();
    await expect(page.getByText("Approve an invoice")).toBeVisible();
  });

  test("a 422 shows the backend message verbatim and leaves the draft untouched", async ({ page }) => {
    await stubShell(page, { workflowGet: EMPTY_CONFIG });
    const DETAIL =
      "These output destinations are not available yet and were not saved: " +
      "drive_archive -- BE Gap 338 (Google Drive write-back). Available now: webhook, dashboard_only, email_summary.";
    await page.route("**/api/settings/workflow", (route) => {
      if (route.request().method() === "GET") return route.fulfill(json(EMPTY_CONFIG));
      if (route.request().method() === "PUT") return route.fulfill(json({ detail: DETAIL }, { status: 422 }));
      return route.fulfill(json({}));
    });

    await page.goto("/settings/workflows", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Where do invoices come in?" })).toBeVisible();
    await option(page, "email").click();
    await page.getByRole("tab", { name: "Review" }).click();

    await page.getByTestId("workflow-save").click();

    await expect(page.getByTestId("workflow-save-error")).toBeVisible();
    await expect(page.getByTestId("workflow-save-error")).toContainText(DETAIL);
    await expect(page.getByTestId("workflow-saved")).toHaveCount(0);

    await page.getByRole("tab", { name: "Input channels" }).click();
    await expect(option(page, "email")).toHaveAttribute("aria-checked", "true");
  });
});
