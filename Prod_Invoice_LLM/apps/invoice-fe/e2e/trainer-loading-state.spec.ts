import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 139 verification — the AI Trainer's document-loading actions must show
 * real processing feedback while a session load is in flight.
 *
 * REWRITTEN FOR FEATURE 14 (FE Gap 235). The original version of this spec
 * stubbed `**\/api/trainer/sessions/global**` (the page's mount session) and
 * `**\/api/trainer/sessions/from-production**` (the Existing Vendor load), and
 * drove the flow through "New Vendor" / "Existing Vendor" buttons on the old
 * control bar. All four of those are gone:
 *
 *   * both endpoints now return 410 Gone on the backend and their proxy routes
 *     have been deleted, so a stub for them would assert against a URL nothing
 *     requests;
 *   * the page no longer opens any session on mount — the landing state is the
 *     document picker, because every session must be anchored to a document the
 *     user chose;
 *   * the scope buttons were replaced by the unified entry panel.
 *
 * What is being verified is unchanged and still real: the loading indicator is
 * on screen for the duration of the wait, and gone once the session lands. The
 * backend call is stubbed with a fixed delay rather than left to a real OCR
 * round-trip so the wait has a known length and the assertion is non-flaky.
 * Same stub-everything approach as the other specs here — needs the Next dev
 * server, no FastAPI backend, no DB.
 */

const STUB_DELAY_MS = 2500;

const SESSION_PAYLOAD = {
  sessionId: "sess-e2e-1",
  scope: "existing_vendor",
  vendorName: "Northwind Freight",
  fileName: "northwind-sample.pdf",
  pdfUrl: "/api/trainer/sessions/sess-e2e-1/pdf",
  createdAt: "2026-08-12T10:00:00Z",
  variables: [],
  activeRules: [],
  activeRulesDetailed: [],
  chatHistory: [],
  sessionMode: "rule_creation",
  invoiceId: "11111111-2222-3333-4444-555555555555",
  flowDirection: "INBOUND",
  alerts: [],
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
        // FE Gap 232: the route now gates on this too. Without it the page
        // renders the permission prompt instead of the workspace.
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
        {
          id: "v1",
          name: "Northwind Freight",
          invoiceCount: 12,
          sampleInvoiceId: "11111111-2222-3333-4444-555555555555",
          sampleFileName: "northwind.pdf",
          samplePdfUrl: "/api/invoices/11111111-2222-3333-4444-555555555555/pdf",
        },
      ]),
    })
  );

  // The vendor's real invoice list — this is what the picker renders, and it is
  // the standard invoice endpoint rather than a trainer one (see
  // trainerService.listVendorInvoices for why).
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "11111111-2222-3333-4444-555555555555",
          invoice_number: "INV-2001",
          vendor_name: "Northwind Freight",
          status: "AUDIT_REQUIRED",
          grand_total: 1240.5,
          currency: "USD",
          created_at: "2026-08-01T09:00:00Z",
          invoice_date: "2026-07-28",
          sa_alerts: [{ type: "tax_mismatch", message: "Tax doesn't reconcile" }],
        },
      ]),
    })
  );
}

/** Fulfil a route only after `STUB_DELAY_MS`, imitating the backend wait. */
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
 * frame was detached`) — a dev-server artefact, not the behaviour under test,
 * so it is retried rather than reported as a failure.
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

test.describe("Gap 139 / Feature 14 — Trainer session loading feedback", () => {
  test("Uploading a PDF shows the staged loading panel until the session lands", async ({
    page,
  }) => {
    await stubTrainer(page);
    await stubSlow(page, "**/api/trainer/upload**", { ...SESSION_PAYLOAD, scope: "new_vendor" });

    await gotoTrainer(page);

    // The landing state is the picker, not a session — nothing is loading yet.
    await expect(page.getByTestId("trainer-entry-panel")).toBeVisible();
    await expect(loadingPanel(page)).toHaveCount(0);

    await page.locator('input[type="file"]').setInputFiles({
      name: "northwind-sample.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 e2e stub"),
    });

    await expect(loadingPanel(page)).toBeVisible();
    await expect(loadingPanel(page)).toContainText("Processing Sample Document");
    await expect(loadingPanel(page)).toContainText("northwind-sample.pdf");
    await expect(loadingPanel(page)).toContainText(/Uploading document|Running OCR/);
    await expect(loadingPanel(page)).toContainText(/%/);

    await expect(loadingPanel(page)).toHaveCount(0, { timeout: STUB_DELAY_MS + 15_000 });
  });

  test("Picking a stored invoice shows the loading panel, then the workspace", async ({
    page,
  }) => {
    await stubTrainer(page);
    await stubSlow(page, "**/api/trainer/sessions/from-invoice**", SESSION_PAYLOAD);

    await gotoTrainer(page);

    // The invoice picker is a real list — the whole point of replacing
    // /sessions/from-production, which could only ever open the newest one.
    await expect(page.getByTestId("trainer-invoice-picker")).toBeVisible();
    await page.getByText("INV-2001").click();

    await expect(loadingPanel(page)).toBeVisible();
    await expect(loadingPanel(page)).toContainText("Loading Production Invoice");
    // The history path runs no OCR, and the copy no longer claims it does.
    await expect(loadingPanel(page)).toContainText(/Opening invoice|Loading stored extraction/);

    await expect(loadingPanel(page)).toHaveCount(0, { timeout: STUB_DELAY_MS + 15_000 });
    await expect(page.getByTestId("trainer-alert-list")).toBeVisible();
  });
});
