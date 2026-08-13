import { test, expect, Page, Locator } from "@playwright/test";

/**
 * FE Gap 112 items 1-4 — Audit Review Console layout + visible corrections.
 *
 * Same approach as group-a-layout-overflow.spec.ts: every /api/** call is
 * stubbed, so this needs the Next dev server but no FastAPI backend, no DB and
 * no seeded tenant. Items 1 and 2 are geometry claims ("three columns",
 * "top-right corner"), so they are asserted against real rendered boxes rather
 * than mere visibility -- a stacked column is still "visible" to Playwright,
 * which is exactly the pre-fix layout this is meant to catch.
 *
 * Items 5-8 of Gap 112 are open product decisions and are deliberately not
 * covered here; the one place they touch this spec is the assertion that an
 * alert naming a non-correctable field (item 6) still gets a plain "Dismiss",
 * which pins the *current* behavior so a future fix has to update it knowingly.
 */

const BASELINE = { width: 1440, height: 900 };
const GEOMETRY_TIMEOUT = 20_000;

// This screen embeds the PDF in an <iframe>, so the document's `load` event
// waits on that too, and under fullyParallel the Next dev server is also
// JIT-compiling the route on first request. Both together blow past the 30s
// default; the assertions themselves settle in well under a second once the
// route is compiled.
test.describe.configure({ timeout: 120_000 });

const INVOICE_ID = "33333333-3333-3333-3333-333333333333";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const INVOICE = {
  id: INVOICE_ID,
  status: "AUDIT_REQUIRED",
  vendor_name: "Hardware Depot",
  invoice_number: "INV-1042",
  invoice_date: "2026-01-15",
  due_date: "2026-02-15",
  grand_total: 1250.5,
  tax_amount: 100.5,
  po_number: "PO-77",
  flow_direction: "INBOUND",
  field_confidence: { InvoiceId: 0.42 },
  coordinates: [],
  items: [
    { description: "Widget A", quantity: 2, unit_price: 500, amount: 1000 },
    { description: "Widget B", quantity: 1, unit_price: 150, amount: 150 },
  ],
  sa_alerts: [
    {
      type: "tax_mismatch",
      message:
        "Subtotal (1150.00) + Tax (100.50) does not match Grand Total (1250.50)",
      // The field key every producer in utils/verification_tools.py already
      // emits -- item 4's alert-to-field link depends on it.
      field: "tax_amount",
    },
    {
      type: "subtotal_not_verified_in_source",
      message:
        "Extracted subtotal (1150.00) was not found verbatim in the source document text.",
      // Gap 112 item 6: `subtotal` is NOT in the backend's correctable
      // allowlist, so this alert must not gain a correction affordance.
      field: "subtotal",
    },
  ],
};

async function stubReviewApis(page: Page, overrides: Record<string, unknown> = {}) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill(
      json({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        // BE Gap 133: the header/admin console now render the backend-resolved
        // tenant name instead of Clerk unsafeMetadata.orgName.
        tenant_name: "E2E Workspace",
        user_id: "user_e2e_admin",
        role: "Admin",
        billing_plan: "active",
        can_train: true,
        can_audit: true,
        can_load: true,
      })
    )
  );
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
        outbound_sender_email: null,
        billing_plan: "free",
      })
    )
  );
  // The bell's count calls -- unstubbed they would hit a backend that isn't up.
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route("**/api/outbound-dashboard/invoices**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  // The PDF iframe: a real request would 404 through to the backend and log
  // noise; an empty 200 keeps the canvas inert without changing its geometry.
  await page.route(`**/api/invoices/${INVOICE_ID}/pdf`, (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
  );
  await page.route(`**/api/invoices/${INVOICE_ID}`, (route) =>
    route.fulfill(json({ ...INVOICE, ...overrides }))
  );
}

// Waiting for the *first* element of a freshly-compiled route is a different
// wait from waiting for layout to settle once it is up: with several workers
// all requesting this route cold, the Next dev server serialises the compile
// and the first paint can be a minute out. Kept separate from
// GEOMETRY_TIMEOUT so the actual assertions stay tight.
const FIRST_PAINT_TIMEOUT = 90_000;

async function settle(page: Page, anchor: Locator) {
  await expect(anchor).toBeVisible({ timeout: FIRST_PAINT_TIMEOUT });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  );
}

async function gotoReview(page: Page, overrides: Record<string, unknown> = {}) {
  await stubReviewApis(page, overrides);
  await page.setViewportSize(BASELINE);
  // `domcontentloaded` rather than the default `load`: the PDF iframe is not
  // what any of these assertions are about, and waiting on it makes every test
  // here hostage to it resolving.
  await page.goto(`/invoices/review/${INVOICE_ID}`, { waitUntil: "domcontentloaded" });
  await settle(page, page.getByRole("heading", { name: "Auditor Review Console" }));
}

// ---------------------------------------------------------------------------
// Item 1 — PDF | Fields | Alerts, three real columns
// ---------------------------------------------------------------------------

test.describe("Gap 112 item 1 — three-column workspace", () => {
  test("PDF, Fields and Alerts sit side by side in that order", async ({ page }) => {
    await gotoReview(page);

    const pdf = page.getByText("Invoice PDF Viewer");
    const fields = page.getByTestId("fields-panel");
    const alerts = page.getByTestId("alerts-panel");

    await expect(fields).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    await expect(alerts).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // The pre-fix layout stacked alerts and fields in one right-hand column,
    // so "all three are visible" would have passed on the bug. Vertical
    // overlap plus strictly increasing x is what actually distinguishes three
    // columns from two columns with a stack in the second.
    await expect
      .poll(
        async () => {
          const p = await pdf.boundingBox();
          const f = await fields.boundingBox();
          const a = await alerts.boundingBox();
          if (!p || !f || !a) return "missing box";
          const sameRow = (x: typeof p, y: typeof p) =>
            x.y < y.y + y.height && y.y < x.y + x.height;
          if (!sameRow(p, f)) return "PDF and Fields are not on the same row";
          if (!sameRow(f, a)) return "Fields and Alerts are not on the same row";
          if (!(p.x < f.x)) return "Fields is not to the right of the PDF";
          if (!(f.x < a.x)) return "Alerts is not to the right of Fields";
          return "three columns";
        },
        {
          timeout: GEOMETRY_TIMEOUT,
          message: "expected PDF -> Fields -> Alerts as three side-by-side columns",
        }
      )
      .toBe("three columns");
  });

  test("no multi-invoice tab/queue strip is rendered (item 3)", async ({ page }) => {
    await gotoReview(page);

    // This route renders exactly one invoice. Nothing may offer to switch to
    // another one from here -- the Audit Queue is that surface.
    await expect(page.getByRole("tablist")).toHaveCount(0);
    await expect(
      page.locator(`a[href^="/invoices/review/"]`).filter({ hasNotText: "INV-1042" })
    ).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Item 2 — Reject / Mark Paid as a compact header pair
// ---------------------------------------------------------------------------

test.describe("Gap 112 item 2 — finalize actions in the header", () => {
  test("Reject and Mark Paid render inside the shared header, top-right", async ({ page }) => {
    await gotoReview(page);

    const header = page.locator("header");
    const reject = header.getByRole("button", { name: "Reject" });
    const markPaid = header.getByRole("button", { name: "Approve Invoice" });

    await expect(reject).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    await expect(markPaid).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // Top-right: both inside the 64px header band, and past the horizontal
    // midpoint. The old buttons were full-width at the bottom of a scrolling
    // column, i.e. the opposite of every property asserted here.
    await expect
      .poll(
        async () => {
          const r = await reject.boundingBox();
          const m = await markPaid.boundingBox();
          if (!r || !m) return "missing box";
          if (r.y + r.height > 64) return `Reject is below the header band (y=${Math.round(r.y)})`;
          if (m.y + m.height > 64) return `Approve Invoice is below the header band (y=${Math.round(m.y)})`;
          if (r.x < BASELINE.width / 2) return "Reject is not in the right half";
          if (!(r.x < m.x)) return "Approve Invoice should follow Reject";
          // "Compact": nothing close to the old full-width bar.
          if (r.width > 200 || m.width > 200) return "buttons are not compact";
          return "compact pair, top-right";
        },
        {
          timeout: GEOMETRY_TIMEOUT,
          message: "Reject/Mark Paid should be a compact pair in the header's right side",
        }
      )
      .toBe("compact pair, top-right");
  });

  test("a resolved invoice offers neither action", async ({ page }) => {
    await gotoReview(page, { status: "PAID", sa_alerts: [] });

    const header = page.locator("header");
    await expect(header.getByRole("button", { name: "Reject" })).toHaveCount(0);
    await expect(header.getByRole("button", { name: "Approve Invoice" })).toHaveCount(0);
    await expect(page.getByText(/has been resolved as/)).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Item 4 — the correction field is actually visible
// ---------------------------------------------------------------------------

test.describe("Gap 112 item 4 — visible inline correction", () => {
  test("clicking a field shows the extracted value struck through, new value editable", async ({
    page,
  }) => {
    await gotoReview(page);

    const taxInput = page.getByTestId("field-Tax Amount").locator("input");
    await taxInput.click();

    const correction = page.getByTestId("field-Tax Amount").getByTestId("inline-correction");
    await expect(correction).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    // The original value, formatted as it is normally displayed.
    await expect(correction).toContainText("$100.50");

    // It must genuinely be struck through, not merely greyed -- that is the
    // whole visual claim of "old value struck through".
    const decoration = await correction
      .locator("span.line-through")
      .evaluate((el) => getComputedStyle(el).textDecorationLine);
    expect(decoration).toContain("line-through");

    // And the new value is editable in place.
    await taxInput.fill("115.00");
    await expect(taxInput).toHaveValue("115.00");
  });

  test("a staged correction previews against its linked alert, whose Dismiss changes label", async ({
    page,
  }) => {
    await gotoReview(page);

    const taxAlert = page
      .getByTestId("audit-alert")
      .filter({ hasText: "does not match Grand Total" });

    // Before any correction, the alert offers a plain Dismiss.
    await expect(taxAlert.getByRole("button", { name: "Dismiss" })).toBeVisible({
      timeout: GEOMETRY_TIMEOUT,
    });
    await expect(taxAlert.getByTestId("alert-correction-preview")).toHaveCount(0);

    const taxInput = page.getByTestId("field-Tax Amount").locator("input");
    await taxInput.click();
    await taxInput.fill("115.00");

    // The alert this field's correction answers now previews old -> new...
    const preview = taxAlert.getByTestId("alert-correction-preview");
    await expect(preview).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    await expect(preview).toContainText("$100.50");
    await expect(preview).toContainText("115.00");

    // ...and its button becomes the combined action.
    await expect(
      taxAlert.getByRole("button", { name: "Dismiss & Save Correction" })
    ).toBeVisible();
  });

  test("an alert on a non-correctable field keeps a plain Dismiss (item 6 still open)", async ({
    page,
  }) => {
    await gotoReview(page);

    const subtotalAlert = page
      .getByTestId("audit-alert")
      .filter({ hasText: "not found verbatim" });

    const taxInput = page.getByTestId("field-Tax Amount").locator("input");
    await taxInput.click();
    await taxInput.fill("115.00");

    // `subtotal` is outside routers/audit.py's _CORRECTABLE_FIELDS, so this
    // alert must not claim a correction of its own even while another field
    // has one staged. Pins current behavior against Gap 112 item 6.
    await expect(subtotalAlert.getByTestId("alert-correction-preview")).toHaveCount(0);
    await expect(subtotalAlert.getByRole("button", { name: "Dismiss" })).toBeVisible();
  });

  test("Revert discards a staged correction", async ({ page }) => {
    await gotoReview(page);

    const field = page.getByTestId("field-Tax Amount");
    const taxInput = field.locator("input");
    await taxInput.click();
    await taxInput.fill("115.00");

    await expect(page.getByText("1 field(s) corrected")).toBeVisible({
      timeout: GEOMETRY_TIMEOUT,
    });

    await field.getByRole("button", { name: "Revert" }).click();

    await expect(page.getByText("1 field(s) corrected")).toHaveCount(0);
    // Blur so the inline correction row closes; it stays open while editing.
    await field.locator("label").click();
    await expect(field.getByTestId("inline-correction")).toHaveCount(0);
  });

  test("an alert's field chip focuses that field in the Fields column", async ({ page }) => {
    await gotoReview(page);

    const taxAlert = page
      .getByTestId("audit-alert")
      .filter({ hasText: "does not match Grand Total" });

    await taxAlert.getByRole("button", { name: "tax_amount →" }).click();

    const taxInput = page.getByTestId("field-Tax Amount").locator("input");
    await expect(taxInput).toBeFocused({ timeout: GEOMETRY_TIMEOUT });
    // Focusing opens the correction row, so the auditor can see what they are
    // changing away from without a second click.
    await expect(
      page.getByTestId("field-Tax Amount").getByTestId("inline-correction")
    ).toBeVisible();
  });
});
