import { test, expect, Page } from "@playwright/test";

/**
 * Gap 282 / Gap 284 / Gap 286 — three independent user-reported FE defects,
 * fixed 2026-08-21.
 *
 *   282: the Outbound Invoices table and the Outbound Auditor Console had no
 *        delete action at all.
 *   284: outbound ingestion opened two "Live Processing Log" boxes per file,
 *        neither of which ever printed anything.
 *   286: the Inbound Auditor Console's "Additional Extracted Metadata" panel
 *        was rendered outside the fields column's scroll container, so a
 *        metadata-rich invoice overflowed the panel and squeezed the extracted
 *        fields out of it.
 *
 * Same approach as the existing specs here: every /api/** call is stubbed, so
 * this needs the Next dev server but no FastAPI backend, DB or seeded tenant.
 * Both layout claims are asserted against real rendered boxes, because the
 * pre-fix DOM was still perfectly "visible" to Playwright — it was mis-sized,
 * not missing.
 */

const BASELINE = { width: 1440, height: 900 };
const GEOMETRY_TIMEOUT = 20_000;
const FIRST_PAINT_TIMEOUT = 90_000;

test.describe.configure({ timeout: 120_000 });

const json = (body: unknown) => ({
  status: 200,
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

/**
 * Catch-all first: Playwright gives precedence to the most recently registered
 * handler, so anything registered after this one wins. Without it the Shell's
 * incidental fetches fall through to a backend that isn't running.
 */
async function stubCommon(page: Page, serviceFlow: Record<string, unknown>) {
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/auth/me", (route) => route.fulfill(json(ME)));
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(json({ outbound_sender_email: null, billing_plan: "free", ...serviceFlow }))
  );
}

// ---------------------------------------------------------------------------
// Gap 286 — Inbound Auditor Console, metadata-heavy invoice
// ---------------------------------------------------------------------------

const INVOICE_ID = "44444444-4444-4444-4444-444444444444";

/**
 * Deliberately loaded up with every extended-metadata list the extraction
 * schema can produce (Gap 205's `taxes` / `tax_ids` / `payment_instructions` /
 * `references` / `compliance_metadata` / `discounts`), including the long
 * opaque values a real Indian e-invoice carries — a 64-char IRN and a signed
 * QR blob. This is the shape that triggered the report; a short two-row
 * metadata block never overflowed anything.
 */
const METADATA_INVOICE = {
  id: INVOICE_ID,
  status: "AUDIT_REQUIRED",
  vendor_name: "Hardware Depot Private Limited",
  invoice_number: "INV-1042",
  invoice_date: "2026-01-15",
  due_date: "2026-02-15",
  grand_total: 1250.5,
  subtotal: 1000,
  tax_amount: 250.5,
  po_number: "PO-77",
  currency: "INR",
  flow_direction: "INBOUND",
  field_confidence: { InvoiceId: 0.42 },
  coordinates: [],
  discount_amount: 50,
  discount_percent: 5,
  items: [
    { description: "Widget A", quantity: 2, unit_price: 500, amount: 1000 },
    { description: "Widget B", quantity: 1, unit_price: 150, amount: 150 },
  ],
  taxes: [
    { tax_type: "CGST", rate_percent: 9, amount: 112.5 },
    { tax_type: "SGST", rate_percent: 9, amount: 112.5 },
    { tax_type: "CESS", rate_percent: 1, amount: 12.5 },
    { tax_type: "TCS", rate_percent: 0.1, amount: 13 },
  ],
  discounts: [
    { discount_type: "Early payment", percent: 2, amount: 20 },
    { discount_type: "Volume", percent: 3, amount: 30 },
  ],
  tax_ids: [
    { id_type: "GSTIN", value: "27AAECH1234F1Z5", party: "Vendor" },
    { id_type: "GSTIN", value: "29AABCU9603R1ZX", party: "Buyer" },
    { id_type: "PAN", value: "AAECH1234F", party: "Vendor" },
  ],
  payment_instructions: [
    { method_type: "Bank Transfer", details: "HDFC Bank, A/C 50200012345678, IFSC HDFC0001234, Branch: MG Road" },
    { method_type: "UPI", details: "hardwaredepot.payments@hdfcbank" },
  ],
  references: [
    { ref_type: "Purchase Order", value: "PO-77" },
    { ref_type: "Delivery Challan", value: "DC-2026-0091" },
  ],
  compliance_metadata: [
    { key: "IRN", value: "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90" },
    { key: "Ack No", value: "112026000123456" },
    { key: "Ack Date", value: "2026-01-15 11:42:00" },
    { key: "Signed QR", value: "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjoie1wiU2VsbGVyR3N0aW5cIjpcIjI3QUFFQ0gxMjM0RjFaNVwifSJ9" },
    { key: "Reverse Charge Applicability", value: "No" },
  ],
  sa_alerts: [
    {
      type: "tax_mismatch",
      message: "Subtotal (1000.00) + Tax (250.50) does not match Grand Total (1250.50)",
      field: "tax_amount",
    },
  ],
};

test.describe("Gap 286 — extended metadata must not squeeze the extracted fields out", () => {
  test.beforeEach(async ({ page }) => {
    await stubCommon(page, { receive_invoices_enabled: true, send_invoices_enabled: false });
    await page.route("**/api/invoices?**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route(`**/api/invoices/${INVOICE_ID}/pdf`, (route) =>
      route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
    );
    await page.route(`**/api/invoices/${INVOICE_ID}`, (route) => route.fulfill(json(METADATA_INVOICE)));

    await page.setViewportSize(BASELINE);
    await page.goto(`/invoices/review/${INVOICE_ID}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Auditor Review Console" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
  });

  test("the metadata panel is reachable by scrolling the fields column, not clipped below it", async ({
    page,
  }) => {
    const fields = page.getByTestId("fields-panel");
    const metadata = page.getByTestId("extracted-metadata-panel");

    await expect(fields).toBeVisible({ timeout: GEOMETRY_TIMEOUT });
    await expect(metadata).toBeAttached();

    // Pre-fix, the metadata panel was a sibling of the scroll container and a
    // direct flex child of this section. `min-height: auto` stopped it
    // shrinking, so it was laid out past the section's own bottom edge and
    // clipped by the grid's `xl:overflow-hidden` -- and because it was outside
    // the scroll container, no amount of scrolling brought it back. Scrolling
    // the column to its end and finding the whole panel inside the column's
    // bounds is exactly the property that was broken.
    const scroller = fields.locator("div.overflow-y-auto").first();
    await scroller.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });

    await expect
      .poll(
        async () => {
          const f = await fields.boundingBox();
          const m = await metadata.boundingBox();
          if (!f || !m) return "missing box";
          // Its top may legitimately be scrolled off above the viewport -- the
          // panel is taller than the column. Its *end* being reachable inside
          // the column is what matters.
          if (m.y + m.height > f.y + f.height + 1) {
            return `metadata ends ${Math.round(m.y + m.height - (f.y + f.height))}px below the fields panel`;
          }
          return "contained";
        },
        {
          timeout: GEOMETRY_TIMEOUT,
          message: "scrolling the fields column to its end should reveal the metadata panel inside it",
        }
      )
      .toBe("contained");

    // Not merely inside the box -- the last metadata row is on screen for the
    // auditor once they scroll there.
    await expect(metadata.getByText("Reverse Charge Applicability")).toBeInViewport();
  });

  test("the correctable fields keep a usable share of the column and stay scrollable", async ({
    page,
  }) => {
    const fields = page.getByTestId("fields-panel");
    await expect(fields).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // Every correctable field is present and the first one is on screen: with
    // the metadata panel competing for height this area collapsed towards zero.
    await expect(page.getByTestId("field-Vendor").locator("input")).toBeVisible();
    for (const label of ["Vendor", "Invoice Number", "Date", "Due Date", "PO Number", "Total Amount", "Tax Amount", "Subtotal"]) {
      await expect(page.getByTestId(`field-${label}`)).toBeAttached();
    }

    const scroller = fields.locator("div.overflow-y-auto").first();
    const metrics = await scroller.evaluate((el) => ({
      client: el.clientHeight,
      scroll: el.scrollHeight,
      containsMetadata: !!el.querySelector('[data-testid="extracted-metadata-panel"]'),
      containsFirstField: !!el.querySelector('[data-testid="field-Vendor"]'),
    }));

    // The metadata now scrolls *with* the fields it belongs to rather than
    // competing with them for the column's height.
    expect(metrics.containsMetadata).toBe(true);
    expect(metrics.containsFirstField).toBe(true);
    // A real, usable viewport for the fields, not a squeezed sliver.
    expect(metrics.client).toBeGreaterThan(250);
    // And the overflow is genuinely reachable by scrolling, not clipped away.
    expect(metrics.scroll).toBeGreaterThan(metrics.client);
  });

  test("long opaque metadata values wrap rather than widening the column", async ({ page }) => {
    const fields = page.getByTestId("fields-panel");
    const metadata = page.getByTestId("extracted-metadata-panel");
    await expect(fields).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // The 64-char IRN and the signed-QR blob are the realistic worst case for
    // a justify-between key/value row.
    const overflowX = await metadata.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflowX).toBeLessThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// Gap 282 — delete action on the outbound table and the outbound console
// ---------------------------------------------------------------------------

const OUTBOUND_A = "55555555-5555-5555-5555-555555555555";
const OUTBOUND_B = "66666666-6666-6666-6666-666666666666";

const OUTBOUND_ROWS = [
  {
    id: OUTBOUND_A,
    invoice_number: "OUT-2001",
    customer_name: "Acme Retail",
    invoice_date: "2026-02-01",
    grand_total: 4200,
    currency: "INR",
    status: "VERIFIED",
    is_overdue: false,
  },
  {
    id: OUTBOUND_B,
    invoice_number: "OUT-2002",
    customer_name: "Beta Foods",
    invoice_date: "2026-02-03",
    grand_total: 990,
    currency: "INR",
    status: "SENT",
    is_overdue: false,
  },
];

test.describe("Gap 282 — outbound invoices can be deleted", () => {
  test("the outbound table offers a delete action that soft-deletes via DELETE /invoices/{id}", async ({
    page,
  }) => {
    await stubCommon(page, { receive_invoices_enabled: true, send_invoices_enabled: true });
    await page.route("**/api/invoices?**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route("**/api/outbound-dashboard/invoices**", (route) =>
      route.fulfill({ ...json(OUTBOUND_ROWS), headers: { "x-total-count": "2" } })
    );

    const deleteCalls: string[] = [];
    await page.route(`**/api/invoices/${OUTBOUND_A}`, (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalls.push(route.request().url());
        return route.fulfill(json({ success: true }));
      }
      return route.fulfill(json(OUTBOUND_ROWS[0]));
    });

    await page.setViewportSize(BASELINE);
    await page.goto("/invoices", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Audit Queue" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });

    await page.locator("header").getByRole("button", { name: "Sending" }).click();
    await expect(page.getByText("Outbound Invoices")).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    // One delete affordance per row -- there were none at all before Gap 282.
    const deleteButtons = page.getByRole("button", { name: /^Delete outbound invoice/ });
    await expect(deleteButtons).toHaveCount(2, { timeout: GEOMETRY_TIMEOUT });

    // Destructive, so it must confirm first: rejecting the dialog must not call.
    page.once("dialog", (d) => d.dismiss());
    await deleteButtons.first().click();
    await page.waitForTimeout(300);
    expect(deleteCalls).toHaveLength(0);

    page.once("dialog", (d) => d.accept());
    await deleteButtons.first().click();
    await expect.poll(() => deleteCalls.length, { timeout: GEOMETRY_TIMEOUT }).toBe(1);
    expect(deleteCalls[0]).toContain(`/api/invoices/${OUTBOUND_A}`);
  });

  test("the outbound review console offers the same delete and returns to the queue", async ({
    page,
  }) => {
    await stubCommon(page, { receive_invoices_enabled: true, send_invoices_enabled: true });
    await page.route("**/api/invoices?**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route("**/api/outbound-dashboard/invoices**", (route) =>
      route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
    );
    await page.route(`**/api/invoices/${OUTBOUND_A}/pdf`, (route) =>
      route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
    );

    const deleteCalls: string[] = [];
    await page.route(`**/api/invoices/${OUTBOUND_A}`, (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalls.push(route.request().url());
        return route.fulfill(json({ success: true }));
      }
      return route.fulfill(
        json({
          ...OUTBOUND_ROWS[0],
          due_date: "2026-03-01",
          tax_amount: 200,
          flow_direction: "OUTBOUND",
          sa_alerts: [],
          items: [],
          coordinates: [],
        })
      );
    });

    await page.setViewportSize(BASELINE);
    await page.goto(`/invoices/outbound-review/${OUTBOUND_A}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Outbound Auditor Console" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });

    const del = page.locator("header").getByRole("button", { name: "Delete" });
    await expect(del).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    page.once("dialog", (d) => d.accept());
    await del.click();

    await expect.poll(() => deleteCalls.length, { timeout: GEOMETRY_TIMEOUT }).toBe(1);
    await expect(page).toHaveURL(/\/invoices$/, { timeout: GEOMETRY_TIMEOUT });
  });
});

// ---------------------------------------------------------------------------
// Gap 284 — one live log box per outbound file, and it actually prints
// ---------------------------------------------------------------------------

const OUTBOUND_BATCH = "77777777-7777-7777-7777-777777777777";
const UPLOADED_INVOICE = "88888888-8888-8888-8888-888888888888";

test.describe("Gap 284 — outbound ingestion opens exactly one live log box", () => {
  test("one LogTerminal per uploaded file, printing the outbound worker's stage events", async ({
    page,
  }) => {
    await stubCommon(page, { receive_invoices_enabled: true, send_invoices_enabled: true });
    await page.route("**/api/connectors/status", (route) =>
      route.fulfill(json({ google_drive: "Inactive" }))
    );
    await page.route("**/api/outbound-invoices/upload", (route) =>
      route.fulfill(json({ invoice_id: UPLOADED_INVOICE, batch_id: OUTBOUND_BATCH }))
    );
    await page.route(`**/api/invoices/${UPLOADED_INVOICE}`, (route) =>
      route.fulfill(
        json({
          id: UPLOADED_INVOICE,
          status: "VERIFIED",
          customer_name: "Acme Retail",
          grand_total: 4200,
          currency: "INR",
          sa_alerts: [],
        })
      )
    );

    // The SSE channel the surviving terminal subscribes to. These are exactly
    // the `{status, message}` events queue_worker/outbound_handlers.py
    // publishes -- it emits no `type: "log_line"` events at all, which is why
    // the box printed nothing before Gap 284.
    const streamHits: string[] = [];
    await page.route("**/api/invoices/stream/**", (route) => {
      streamHits.push(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: ${JSON.stringify({ status: "PROCESSING_OCR", message: "Extracting text from outbound invoice PDF..." })}\n\n` +
          `data: ${JSON.stringify({ status: "EXTRACTING_DATA", message: "Extracting structured fields using LLM..." })}\n\n` +
          `data: ${JSON.stringify({ status: "VERIFIED", message: "Outbound processing finished with status: VERIFIED", invoice_id: UPLOADED_INVOICE })}\n\n`,
      });
    });

    await page.setViewportSize(BASELINE);
    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "File Ingestion" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });

    await page.locator("header").getByRole("button", { name: "Sending" }).click();
    await expect(page.getByText("Upload Outbound Invoice")).toBeVisible({ timeout: GEOMETRY_TIMEOUT });

    await page.locator('input[type="file"]').first().setInputFiles({
      name: "outbound-one.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 e2e"),
    });
    await page.getByRole("button", { name: /Upload & Extract/ }).click();

    // One file uploaded => exactly one live log box. Before the fix there were
    // two: SendInvoiceStatusTable embedded its own (keyed on the *invoice* id,
    // which the stream endpoint resolves as a batch id and so always 404'd)
    // alongside the page-level one keyed on the real batch id.
    const terminals = page.getByTestId("log-terminal");
    await expect(terminals).toHaveCount(1, { timeout: GEOMETRY_TIMEOUT });

    // ...and the one that survives is subscribed to the batch id, not the
    // invoice id.
    await expect.poll(() => streamHits.length, { timeout: GEOMETRY_TIMEOUT }).toBeGreaterThan(0);
    expect(streamHits.every((u) => u.includes(OUTBOUND_BATCH))).toBe(true);
    expect(streamHits.some((u) => u.includes(UPLOADED_INVOICE))).toBe(false);

    // And it is no longer a dead box.
    await expect(terminals).toContainText("Extracting text from outbound invoice PDF...", {
      timeout: GEOMETRY_TIMEOUT,
    });
    await expect(terminals).toContainText("Outbound processing finished with status: VERIFIED");
    await expect(page.getByText("Waiting for processing to start...")).toHaveCount(0);
  });
});
