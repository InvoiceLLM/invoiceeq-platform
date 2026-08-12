import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 139 verification — the AI Trainer's document-loading actions must show
 * real processing feedback while a session load is in flight.
 *
 * Before the fix, `app/trainer/page.tsx`'s `handleSelectVendor` /
 * `handleUploadFile` / `handleClearFile` awaited their backend call with no
 * loading state at all, and `PdfViewerPanel.tsx` had nowhere to render one, so
 * the screen sat unchanged for the whole OCR + extraction round-trip.
 *
 * The backend call is deliberately stubbed with a fixed delay rather than left
 * to a real OCR round-trip: the assertion is "the indicator is on screen for
 * the duration of the wait, and gone once the session lands", which needs a
 * wait of known length to be non-flaky. Same stub-everything approach as the
 * other specs here — needs the Next dev server, no FastAPI backend, no DB.
 */

const STUB_DELAY_MS = 2500;

const SESSION_PAYLOAD = {
  sessionId: "sess-e2e-1",
  scope: "new_vendor",
  vendorName: "Northwind Freight",
  createdAt: "2026-08-12T10:00:00Z",
  variables: [],
  activeRules: [],
  chatHistory: [],
};

async function stubTrainer(page: Page) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        tenant_name: "E2E Workspace",
        user_id: "user_e2e",
        // In TRAINER_PLANS, so the page renders the sandbox rather than the
        // Gap 115 upgrade prompt.
        billing_plan: "active",
        role: "Admin",
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
        receive_invoices_enabled: true,
        send_invoices_enabled: true,
        billing_plan: "pro_combined",
      }),
    })
  );

  await page.route("**/api/trainer/vendors**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "v1", name: "Northwind Freight", invoiceCount: 12 },
      ]),
    })
  );

  // The page's own mount session — resolves immediately, so the loading mode
  // asserted below can only come from the action under test.
  await page.route("**/api/trainer/sessions/global**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...SESSION_PAYLOAD, scope: "global" }),
    })
  );
}

/** Fulfil a route only after `STUB_DELAY_MS`, imitating the OCR + LLM wait. */
async function stubSlow(page: Page, pattern: string, payload: unknown) {
  await page.route(pattern, async (route) => {
    await new Promise((r) => setTimeout(r, STUB_DELAY_MS));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
}

const loadingPanel = (page: Page) => page.getByTestId("trainer-pdf-loading");

/**
 * The very first navigation to /trainer in a run can be aborted by the Next dev
 * server while it is still JIT-compiling the route (`net::ERR_ABORTED; maybe
 * frame was detached`) — observed reliably on whichever of these two tests runs
 * first, and never on the second. That is a dev-server artefact, not the
 * behaviour under test, so it is retried rather than reported as a failure.
 * (Same class of problem the geometry specs handle with expect.poll.)
 */
async function gotoTrainer(page: Page) {
  for (let attempt = 0; ; attempt++) {
    try {
      await page.goto("/trainer", { waitUntil: "domcontentloaded", timeout: 60_000 });
      break;
    } catch (err) {
      if (attempt >= 2) throw err;
    }
  }
  await expect(page.locator("header h1")).toHaveText("AI Trainer", { timeout: 60_000 });
}

test.describe("Gap 139 — Trainer session loading feedback", () => {
  test("New Vendor upload shows the staged loading panel until the session lands", async ({
    page,
  }) => {
    await stubTrainer(page);
    await stubSlow(page, "**/api/trainer/upload**", SESSION_PAYLOAD);

    await gotoTrainer(page);

    await page.getByRole("button", { name: "New Vendor" }).click();
    // Nothing is loading yet — the empty New Vendor sandbox card is showing.
    await expect(loadingPanel(page)).toHaveCount(0);

    await page.locator('input[type="file"]').setInputFiles({
      name: "northwind-sample.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 e2e stub"),
    });

    // The panel appears, names the file being processed, and reports a real
    // stage + percentage rather than an inert spinner.
    await expect(loadingPanel(page)).toBeVisible();
    await expect(loadingPanel(page)).toContainText("Processing Sample Document");
    await expect(loadingPanel(page)).toContainText("northwind-sample.pdf");
    await expect(loadingPanel(page)).toContainText(/Uploading document|Running OCR/);
    await expect(loadingPanel(page)).toContainText(/%/);

    // And it clears once the (stubbed) session actually arrives.
    await expect(loadingPanel(page)).toHaveCount(0, { timeout: STUB_DELAY_MS + 15_000 });
  });

  test("Existing Vendor production load shows the loading panel, not the previous state", async ({
    page,
  }) => {
    await stubTrainer(page);
    await stubSlow(page, "**/api/trainer/sessions/from-production**", {
      ...SESSION_PAYLOAD,
      scope: "existing_vendor",
    });

    await gotoTrainer(page);

    await page.getByRole("button", { name: "Existing Vendor" }).click();
    await page
      .locator("#trainer-grounding-vendor")
      .selectOption({ label: "Northwind Freight (12)" });

    await expect(loadingPanel(page)).toBeVisible();
    await expect(loadingPanel(page)).toContainText("Loading Production Invoice");
    await expect(loadingPanel(page)).toContainText(/Fetching production invoice|Running OCR/);

    await expect(loadingPanel(page)).toHaveCount(0, { timeout: STUB_DELAY_MS + 15_000 });
  });
});
