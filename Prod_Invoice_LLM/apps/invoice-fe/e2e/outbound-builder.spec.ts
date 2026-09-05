import { test, expect, Page } from "@playwright/test";

/**
 * Feature 20, task 20.6 — the Invoice Builder (clone & edit) screen and its two
 * entry points.
 *
 * Same approach as every other spec in this directory: each `/api/**` call is
 * stubbed with `page.route()`, so this needs the Next dev server but no
 * FastAPI backend, database or seeded tenant. That is not only convenience
 * here — BE Feature 17's endpoints were being built in parallel with this
 * screen and did not exist when the spec was written, so the *contract* is what
 * is under test:
 *
 *   GET  /api/outbound-invoices/{id}/build-defaults  → BuildRequest | 404 | 409
 *   POST /api/outbound-invoices/build/preview        → application/pdf | 409 | 422
 *   POST /api/outbound-invoices/build                → {batch_id, invoice_id}
 *
 * If the backend ever answers differently from the fixtures below, this spec
 * keeps passing while the real screen breaks — so a live end-to-end run against
 * the dev stack is still owed (see the spec's Verification Plan, row 20.6).
 */

const BASELINE = { width: 1440, height: 900 };
const ACTION_TIMEOUT = 20_000;
const FIRST_PAINT_TIMEOUT = 90_000;

test.describe.configure({ timeout: 120_000 });

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const ME = {
  tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  tenant_name: "E2E Workspace",
  user_id: "user_e2e_admin",
  role: "Admin",
  billing_plan: "active",
  can_train: true,
  can_audit: true,
  can_load: true,
};

const SOURCE_ID = "11111111-1111-1111-1111-111111111111";
const CLONE_ID = "22222222-2222-2222-2222-222222222222";
const REVIEW_ID = "33333333-3333-3333-3333-333333333333";
const BATCH_ID = "99999999-9999-9999-9999-999999999999";

/** Two rows, one line item each, so a preview is one round-trip. */
const BUILD_DEFAULTS = {
  source_invoice_id: SOURCE_ID,
  customer_name: "Northwind Traders",
  invoice_number: "INV-1043",
  invoice_date: "2026-02-01",
  due_date: "2026-03-03",
  currency: "USD",
  tax_amount: "10.00",
  items: [
    { description: "Consulting hours", quantity: "3", unit_price: "19.99" },
    { description: "Support retainer", quantity: "1", unit_price: "100" },
  ],
};

/**
 * The smallest byte string the preview route can hand back. `PdfViewerCanvas`
 * only ever puts the URL in an `<iframe src>`, so Chromium's PDF plugin never
 * has to parse this — the assertion is that a blob URL reached the viewer.
 */
const PDF_BYTES = "%PDF-1.4\n%%EOF\n";

/**
 * Catch-all first: Playwright prefers the most recently registered handler, so
 * everything registered after this wins. Without it the Shell's incidental
 * fetches fall through to a backend that is not running.
 */
async function stubCommon(page: Page) {
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/auth/me", (route) => route.fulfill(json(ME)));
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        receive_invoices_enabled: true,
        send_invoices_enabled: true,
        outbound_sender_email: null,
        billing_plan: "free",
      })
    )
  );
}

async function stubBuildDefaults(page: Page, response = json(BUILD_DEFAULTS)) {
  await page.route(`**/api/outbound-invoices/${SOURCE_ID}/build-defaults`, (route) =>
    route.fulfill(response)
  );
}

async function openBuilder(page: Page) {
  await page.setViewportSize(BASELINE);
  await page.goto(`/invoices/outbound-builder?source=${SOURCE_ID}`, {
    waitUntil: "domcontentloaded",
  });
}

// ---------------------------------------------------------------------------
// Prefill, totals and the layout pill (tasks 20.2 / 20.3)
// ---------------------------------------------------------------------------

test.describe("Invoice Builder — defaults, totals, layout pill", () => {
  test("defaults populate every header field and the line-item grid", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await openBuilder(page);

    await expect(page.getByTestId("builder-form")).toBeVisible({ timeout: FIRST_PAINT_TIMEOUT });
    await expect(page.getByTestId("builder-input-customer-name")).toHaveValue("Northwind Traders");
    await expect(page.getByTestId("builder-input-invoice-number")).toHaveValue("INV-1043");
    await expect(page.getByTestId("builder-input-invoice-date")).toHaveValue("2026-02-01");
    await expect(page.getByTestId("builder-input-due-date")).toHaveValue("2026-03-03");
    // Currency is copied, never editable in v1 — the substitution renderer has
    // nowhere to put a different symbol.
    await expect(page.getByTestId("builder-input-currency")).toHaveValue("USD");
    await expect(page.getByTestId("builder-input-currency")).toHaveAttribute("readonly", "");

    await expect(page.getByTestId("line-item-row-0")).toBeVisible();
    await expect(page.getByTestId("item-description-0")).toHaveValue("Consulting hours");
    await expect(page.getByTestId("item-description-1")).toHaveValue("Support retainer");
  });

  test("totals mirror BE compute_totals and update on every keystroke", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await openBuilder(page);

    // 3 x 19.99 = 59.97, plus 1 x 100, plus 10.00 tax.
    await expect(page.getByTestId("item-amount-0")).toHaveText("$59.97", {
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await expect(page.getByTestId("totals-subtotal")).toHaveText("$159.97");
    await expect(page.getByTestId("totals-grand-total")).toHaveText("$169.97");

    await page.getByTestId("item-quantity-0").fill("4");
    await expect(page.getByTestId("item-amount-0")).toHaveText("$79.96");
    await expect(page.getByTestId("totals-subtotal")).toHaveText("$179.96");
    await expect(page.getByTestId("totals-grand-total")).toHaveText("$189.96");
  });

  test("adding or removing a row flips the layout pill to re-rendered", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await openBuilder(page);

    const pill = page.getByTestId("layout-pill");
    await expect(pill).toHaveAttribute("data-render-mode", "substitute", {
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await expect(pill).toHaveText(/exact copy/);

    await page.getByTestId("add-row").click();
    await expect(pill).toHaveAttribute("data-render-mode", "rerender");
    await expect(pill).toHaveText(/re-rendered/);

    // Back to the source's row count → substitution is available again.
    await page.getByTestId("remove-row-2").click();
    await expect(pill).toHaveAttribute("data-render-mode", "substitute");

    // Removing below the source count is still "re-rendered", not "exact copy".
    await page.getByTestId("remove-row-1").click();
    await expect(pill).toHaveAttribute("data-render-mode", "rerender");
  });
});

// ---------------------------------------------------------------------------
// Preview, 409 and 422 (task 20.4)
// ---------------------------------------------------------------------------

test.describe("Invoice Builder — preview", () => {
  test("a 200 application/pdf renders in the PDF viewer", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await page.route("**/api/outbound-invoices/build/preview", (route) =>
      route.fulfill({ status: 200, contentType: "application/pdf", body: PDF_BYTES })
    );
    await openBuilder(page);

    await expect(page.getByTestId("preview-placeholder")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await page.getByTestId("preview-button").click();

    const frame = page.locator("iframe").first();
    await expect(frame).toBeVisible({ timeout: ACTION_TIMEOUT });
    // The preview PDF has never been stored, so it must be a blob URL rather
    // than /api/invoices/{id}/pdf — that is the whole point of the srcUrl prop.
    await expect(frame).toHaveAttribute("src", /^blob:/);
    await expect(page.getByTestId("preview-placeholder")).toHaveCount(0);
  });

  test("editing after a preview marks it stale", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await page.route("**/api/outbound-invoices/build/preview", (route) =>
      route.fulfill({ status: 200, contentType: "application/pdf", body: PDF_BYTES })
    );
    await openBuilder(page);

    await page.getByTestId("preview-button").click({ timeout: FIRST_PAINT_TIMEOUT });
    await expect(page.locator("iframe").first()).toBeVisible({ timeout: ACTION_TIMEOUT });
    await expect(page.getByTestId("preview-stale")).toHaveCount(0);

    await page.getByTestId("item-quantity-0").fill("9");
    await expect(page.getByTestId("preview-stale")).toBeVisible();
  });

  test("a 409 duplicate number is shown against the invoice number field", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await page.route("**/api/outbound-invoices/build/preview", (route) =>
      route.fulfill(json({ detail: "Invoice number already used for this customer" }, 409))
    );
    await openBuilder(page);

    await page.getByTestId("preview-button").click({ timeout: FIRST_PAINT_TIMEOUT });

    // Founder decision D5: the message belongs next to the field the user has
    // to change, not in a page-level banner.
    await expect(page.getByTestId("builder-error-invoice-number")).toHaveText(
      "Invoice number already used for this customer",
      { timeout: ACTION_TIMEOUT }
    );
    await expect(page.locator("iframe")).toHaveCount(0);
  });

  test("a 422 marks the unlocated fields and revert-to-source restores them", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await page.route("**/api/outbound-invoices/build/preview", (route) =>
      route.fulfill(json({ unlocated_fields: ["customer_name"] }, 422))
    );
    await openBuilder(page);

    await page.getByTestId("builder-input-customer-name").fill("Contoso Ltd", {
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await page.getByTestId("preview-button").click();

    await expect(page.getByTestId("unlocated-fields")).toContainText("customer_name", {
      timeout: ACTION_TIMEOUT,
    });

    // One click puts the source's own value back, which is always substitutable
    // because it is already what the source PDF prints.
    await page.getByTestId("builder-revert-customer-name").click();
    await expect(page.getByTestId("builder-input-customer-name")).toHaveValue("Northwind Traders");
    await expect(page.getByTestId("builder-revert-customer-name")).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Create and load failures (task 20.3)
// ---------------------------------------------------------------------------

test.describe("Invoice Builder — create", () => {
  test("create posts the form and routes to the Sending ledger", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);

    let posted: any = null;
    await page.route("**/api/outbound-invoices/build", (route) => {
      posted = JSON.parse(route.request().postData() || "null");
      return route.fulfill(json({ batch_id: BATCH_ID, invoice_id: CLONE_ID }));
    });

    await openBuilder(page);
    await page.getByTestId("item-quantity-0").fill("5", { timeout: FIRST_PAINT_TIMEOUT });
    await page.locator("header").getByTestId("create-invoice").click();

    await expect(page).toHaveURL(new RegExp(`/ingestion\\?.*builtInvoice=${CLONE_ID}`), {
      timeout: ACTION_TIMEOUT,
    });
    expect(posted).toBeTruthy();
    expect(posted.source_invoice_id).toBe(SOURCE_ID);
    expect(posted.items[0].quantity).toBe("5");
    // Display-only totals are never sent — the BE recomputes them.
    expect(posted.subtotal).toBeUndefined();
    expect(posted.grand_total).toBeUndefined();
    expect(posted.items[0].amount).toBeUndefined();
  });

  test("the Sending hand-off opens the Sending tab with the new invoice in the ledger", async ({
    page,
  }) => {
    // FE Gap 457: /ingestion read none of these params, so the builder's
    // redirect used to land on Receiving with an idle outbound ledger.
    await stubCommon(page);
    // /ingestion's Sending tab needs the per-user permission on top of the
    // tenant-wide service-flow flag (Gap 405); registered after stubCommon so
    // it wins over that ME fixture.
    await page.route("**/api/auth/me", (route) =>
      route.fulfill(json({ ...ME, can_send_invoices: true }))
    );
    await page.route(`**/api/invoices/${CLONE_ID}`, (route) =>
      route.fulfill(
        json({
          id: CLONE_ID,
          status: "PROCESSING",
          invoice_number: "INV-1043",
          flow_direction: "OUTBOUND",
        })
      )
    );

    await page.setViewportSize(BASELINE);
    await page.goto(
      `/ingestion?tab=sending&builtInvoice=${CLONE_ID}&batch=${BATCH_ID}&name=INV-1043`,
      { waitUntil: "domcontentloaded" }
    );

    // Sending, not Receiving. The tab's own upload panel is asserted first --
    // it only renders under `showSending`, and waiting on it means the header
    // tab button below is read after hydration rather than during it.
    await expect(page.getByText("Upload Outbound Invoice")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await expect(page.locator("header").getByRole("button", { name: "Sending" })).toHaveClass(
      /bg-\[#3B82F6\]/,
      { timeout: ACTION_TIMEOUT }
    );

    // ...and the seeded row is there instead of the empty state.
    await expect(page.getByText("Outbound Ledger Idle")).toHaveCount(0);
    await expect(page.getByText("INV-1043").first()).toBeVisible({ timeout: ACTION_TIMEOUT });
  });

  test("a 409 on create is shown inline and does not navigate", async ({ page }) => {
    await stubCommon(page);
    await stubBuildDefaults(page);
    await page.route("**/api/outbound-invoices/build", (route) =>
      route.fulfill(json({ detail: "Invoice number already used for this customer" }, 409))
    );

    await openBuilder(page);
    await page.locator("header").getByTestId("create-invoice").click({ timeout: FIRST_PAINT_TIMEOUT });

    await expect(page.getByTestId("create-error")).toBeVisible({ timeout: ACTION_TIMEOUT });
    await expect(page.getByTestId("builder-error-invoice-number")).toBeVisible();
    await expect(page).toHaveURL(/outbound-builder/);
  });

  test("a 409 from build-defaults explains the eligibility rule instead of an empty form", async ({
    page,
  }) => {
    await stubCommon(page);
    await stubBuildDefaults(
      page,
      json({ detail: "Only verified, sent, paid or overdue invoices can be cloned" }, 409)
    );
    await openBuilder(page);

    await expect(page.getByTestId("builder-load-error")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await expect(page.getByTestId("builder-load-error")).toContainText("cloned");
    await expect(page.getByTestId("builder-form")).toHaveCount(0);
  });

  test("no ?source= at all is an error, not a blank builder", async ({ page }) => {
    await stubCommon(page);
    await page.setViewportSize(BASELINE);
    await page.goto("/invoices/outbound-builder", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("builder-load-error")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await expect(page.getByTestId("builder-form")).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Entry points (task 20.5)
// ---------------------------------------------------------------------------

const OUTBOUND_ROWS = [
  {
    id: SOURCE_ID,
    invoice_number: "INV-1042",
    customer_name: "Northwind Traders",
    invoice_date: "2026-01-15",
    grand_total: 1250.5,
    currency: "USD",
    status: "VERIFIED",
    is_overdue: false,
  },
  {
    id: REVIEW_ID,
    invoice_number: "INV-1050",
    customer_name: "Contoso Ltd",
    invoice_date: "2026-01-20",
    grand_total: 400,
    currency: "USD",
    status: "NEEDS_REVIEW",
    is_overdue: false,
  },
  {
    id: CLONE_ID,
    invoice_number: "INV-1043",
    customer_name: "Northwind Traders",
    invoice_date: "2026-02-01",
    grand_total: 169.97,
    currency: "USD",
    status: "VERIFIED",
    is_overdue: false,
    // BE task 17.7 adds this to the outbound list response.
    source_invoice_id: SOURCE_ID,
  },
];

test.describe("Invoice Builder — entry points", () => {
  test("the outbound table offers Clone on eligible rows only, and links a clone to its source", async ({
    page,
  }) => {
    await stubCommon(page);
    await page.route("**/api/invoices?**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route("**/api/outbound-dashboard/invoices**", (route) =>
      route.fulfill({ ...json(OUTBOUND_ROWS), headers: { "x-total-count": "3" } })
    );

    await page.setViewportSize(BASELINE);
    await page.goto("/invoices", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Audit Queue" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await page.locator("header").getByRole("button", { name: "Sending" }).click();
    await expect(page.getByText("Outbound Invoices")).toBeVisible({ timeout: ACTION_TIMEOUT });

    // Founder decision D4: VERIFIED yes, NEEDS_REVIEW no.
    await expect(page.getByTestId(`clone-invoice-${SOURCE_ID}`)).toBeVisible();
    await expect(page.getByTestId(`clone-invoice-${CLONE_ID}`)).toBeVisible();
    await expect(page.getByTestId(`clone-invoice-${REVIEW_ID}`)).toHaveCount(0);

    // Lineage renders only on the row that carries source_invoice_id.
    await expect(page.getByTestId(`cloned-from-${CLONE_ID}`)).toBeVisible();
    await expect(page.getByTestId(`cloned-from-${SOURCE_ID}`)).toHaveCount(0);
    await expect(page.getByTestId(`cloned-from-${CLONE_ID}`)).toHaveAttribute(
      "href",
      `/invoices/outbound-review/${SOURCE_ID}`
    );

    await stubBuildDefaults(page);
    await page.getByTestId(`clone-invoice-${SOURCE_ID}`).click();
    await expect(page).toHaveURL(
      new RegExp(`/invoices/outbound-builder\\?source=${SOURCE_ID}`),
      { timeout: ACTION_TIMEOUT }
    );
  });

  for (const [status, visible] of [
    ["VERIFIED", true],
    ["SENT", true],
    ["PAID", true],
    ["NEEDS_REVIEW", false],
  ] as const) {
    test(`the outbound review header ${visible ? "offers" : "hides"} "New invoice from this" on ${status}`, async ({
      page,
    }) => {
      await stubCommon(page);
      await page.route(`**/api/invoices/${SOURCE_ID}/pdf`, (route) =>
        route.fulfill({ status: 200, contentType: "application/pdf", body: PDF_BYTES })
      );
      await page.route(`**/api/invoices/${SOURCE_ID}`, (route) =>
        route.fulfill(
          json({
            id: SOURCE_ID,
            status,
            customer_name: "Northwind Traders",
            invoice_number: "INV-1042",
            invoice_date: "2026-01-15",
            due_date: "2026-02-15",
            grand_total: 1250.5,
            tax_amount: 200,
            currency: "USD",
            flow_direction: "OUTBOUND",
            sa_alerts: [],
            items: [],
            coordinates: [],
          })
        )
      );

      await page.setViewportSize(BASELINE);
      await page.goto(`/invoices/outbound-review/${SOURCE_ID}`, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: "Outbound Auditor Console" })).toBeVisible({
        timeout: FIRST_PAINT_TIMEOUT,
      });

      const clone = page.locator("header").getByTestId("clone-invoice");
      if (visible) {
        await expect(clone).toBeVisible({ timeout: ACTION_TIMEOUT });
        await expect(clone).toHaveAttribute(
          "href",
          `/invoices/outbound-builder?source=${SOURCE_ID}`
        );
      } else {
        await expect(clone).toHaveCount(0);
      }
    });
  }
});
