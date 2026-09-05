import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 378 — Feature 27 (Generic Document Extraction), task G11: the FE
 * surfaces for `doc_type`.
 *
 * What these specs are actually guarding. Backend task G9 (`Invoice.doc_type` /
 * `Invoice.doc_type_evidence`) has NOT landed — `models.py` has no such column
 * today — and even once it does, Feature 27 specifies both fields nullable and
 * `ENABLE_GENERIC_EXTRACTION` off by default. So the field is absent from every
 * real API response right now, and the load-bearing claim is the *regression*
 * one: with no `doc_type` anywhere, the ingestion ledger and the auditor
 * console render exactly as they did before this change. The present-case tests
 * exist so that claim isn't trivially true because the badge was never wired up
 * at all.
 *
 * Same approach as the existing specs here (see gaps-282-284-286.spec.ts):
 * every /api/** call is stubbed, so this needs the Next dev server but no
 * FastAPI backend, DB or seeded tenant.
 */

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
 * handler, so anything registered after this one wins.
 */
async function stubCommon(page: Page) {
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/auth/me", (route) => route.fulfill(json(ME)));
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        outbound_sender_email: null,
        billing_plan: "free",
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
      })
    )
  );
}

// ---------------------------------------------------------------------------
// Ingestion status ledger — StatusTable.tsx
// ---------------------------------------------------------------------------

const BATCH_ID = "77777777-7777-7777-7777-777777777777";
const JOB_ID = "88888888-8888-8888-8888-888888888888";

/**
 * The status payload as `GET /invoices/status/{id}` returns it today —
 * deliberately with no `doc_type` key at all, not `doc_type: null`, because
 * "the column does not exist yet" is the real shape being defended.
 */
const STATUS_WITHOUT_DOC_TYPE = {
  id: JOB_ID,
  status: "COMPLETED",
  alerts: [],
  vendor_name: "Hardware Depot Private Limited",
  grand_total: 1250.5,
  currency: "INR",
};

const STATUS_WITH_DOC_TYPE = {
  ...STATUS_WITHOUT_DOC_TYPE,
  doc_type: "DELIVERY_NOTE",
};

/**
 * `/ingestion` is server-rendered, so the DropZone's hidden input is in the DOM
 * (and `toBeAttached()` passes) several seconds before React hydrates and binds
 * its `onChange`. Setting files in that window is silently dropped — the file
 * lands on the input and no handler ever runs. So: set, check the component
 * actually reacted, retry. This is a hydration race in the test, not a defect
 * in the component.
 */
async function selectFileWhenHydrated(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
  reacted: () => Promise<void>
) {
  // FE Feature 19 widened the accept list, so this can no longer key off
  // `accept=".pdf"`. The exact value is asserted in
  // e2e/ingestion-image-upload.spec.ts; here it is just a way to find the input.
  const dropZoneInput = page.locator('input[type="file"]').first();
  await expect(dropZoneInput).toBeAttached({ timeout: FIRST_PAINT_TIMEOUT });

  await expect(async () => {
    await dropZoneInput.setInputFiles(file);
    await reacted();
  }).toPass({ timeout: 60_000, intervals: [500, 1000, 2000] });
}

async function uploadOneFile(page: Page, statusPayload: unknown) {
  await page.route("**/api/invoices/upload", (route) =>
    route.fulfill(json({ batch_id: BATCH_ID, job_ids: [JOB_ID] }))
  );
  await page.route("**/api/invoices/status/**", (route) => route.fulfill(json(statusPayload)));

  await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

  const submit = page.getByRole("button", { name: "Submit Ingestion Batch" });
  await selectFileWhenHydrated(
    page,
    { name: "delivery-note.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 e2e") },
    async () => {
      await expect(submit).toBeEnabled({ timeout: 3_000 });
    }
  );

  await submit.click();
  await expect(page.getByText("Ingestion Progress Queue")).toBeVisible({
    timeout: FIRST_PAINT_TIMEOUT,
  });
}

test.describe("FE Gap 378 — ingestion ledger doc-type badge", () => {
  test.beforeEach(async ({ page }) => {
    await stubCommon(page);
  });

  test("renders exactly as today when no row carries a doc_type", async ({ page }) => {
    await uploadOneFile(page, STATUS_WITHOUT_DOC_TYPE);

    // The row is there and reconciled — so the absence below is "no badge",
    // not "no data".
    await expect(page.getByText("delivery-note.pdf")).toBeVisible();
    await expect(page.getByText("Completed")).toBeVisible();

    // The regression claim: nothing new is drawn anywhere in the ledger.
    await expect(page.getByTestId("doc-type-badge")).toHaveCount(0);

    // And no column header was added — the ledger is still File / Stage /
    // Status, which is what FE Gap 113 item 6 deliberately reduced it to.
    const headers = page.locator("table thead th");
    await expect(headers).toHaveCount(3);
    await expect(headers.nth(0)).toHaveText("File");
    await expect(headers.nth(1)).toHaveText("Stage");
    await expect(headers.nth(2)).toHaveText("Status");
  });

  test("renders the badge, humanised, when a row carries a doc_type", async ({ page }) => {
    await uploadOneFile(page, STATUS_WITH_DOC_TYPE);

    const badge = page.getByTestId("doc-type-badge");
    await expect(badge).toHaveCount(1);
    // DELIVERY_NOTE -> "Delivery Note": the enum value is for the API, not for
    // the person reading the ledger. The raw value stays in the title attr so
    // a misclassification is still reportable verbatim.
    await expect(badge).toHaveText("Delivery Note");
    await expect(badge).toHaveAttribute(
      "title",
      "Document type classified by extraction: DELIVERY_NOTE"
    );

    // Still three columns — the badge lives inside the File cell.
    await expect(page.locator("table thead th")).toHaveCount(3);
  });
});

// ---------------------------------------------------------------------------
// DropZone — the accept list is deliberately unchanged
// ---------------------------------------------------------------------------

/**
 * SUPERSEDED BY FE FEATURE 19 (2026-09-04). This block used to assert the
 * DropZone was still PDF-only, on the reasoning that Feature 27 widens the list
 * only behind ENABLE_GENERIC_EXTRACTION. That reasoning was correct for
 * Feature 27 and is now incomplete: BE Feature 28 converts images to PDF at the
 * door with NO flag (decision D1), so the image suffixes are offered
 * unconditionally and the two lists compose.
 *
 * The assertion is not deleted, it is inverted and moved: the accept attribute,
 * both guards, and the copy are covered in
 * e2e/ingestion-image-upload.spec.ts. What remains here is the part that is
 * still Feature 27's claim — the flag's own list is never *replaced*, only
 * unioned, so nothing this spec's feature relies on was narrowed.
 */
test.describe("FE Gap 378 — Feature 27's accept list survives Feature 19's widening", () => {
  test("every ENABLE_GENERIC_EXTRACTION suffix is still offered", async ({ page }) => {
    await stubCommon(page);
    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

    const dropZoneInput = page.locator('input[type="file"]').first();
    await expect(dropZoneInput).toBeAttached({ timeout: FIRST_PAINT_TIMEOUT });

    const accept = (await dropZoneInput.getAttribute("accept")) ?? "";
    for (const ext of [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"]) {
      expect(accept.split(",")).toContain(ext);
    }
  });

  test("a format outside both lists is still rejected by the suffix guard", async ({ page }) => {
    await stubCommon(page);
    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

    // Guard 1 (the suffix check) must agree with guard 2, or a dragged file
    // gets past the picker and is rejected only after selection.
    await selectFileWhenHydrated(
      page,
      { name: "packing-slip.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") },
      async () => {
        await expect(page.getByText("Invalid file format.", { exact: false })).toBeVisible({
          timeout: 3_000,
        });
      }
    );
  });
});

// ---------------------------------------------------------------------------
// Auditor review console — doc_type + doc_type_evidence
// ---------------------------------------------------------------------------

const INVOICE_ID = "99999999-9999-9999-9999-999999999999";

/**
 * Deliberately metadata-free apart from the two fields under test: no taxes,
 * no tax_ids, no compliance_metadata, no currency. That makes the panel's own
 * visibility the assertion — pre-change, this record rendered no "Additional
 * Extracted Metadata" panel at all.
 */
const PLAIN_INVOICE = {
  id: INVOICE_ID,
  status: "AUDIT_REQUIRED",
  vendor_name: "Hardware Depot Private Limited",
  invoice_number: "INV-1042",
  invoice_date: "2026-01-15",
  due_date: null,
  grand_total: 1250.5,
  subtotal: 1000,
  tax_amount: 250.5,
  po_number: null,
  flow_direction: "INBOUND",
  field_confidence: {},
  coordinates: [],
  items: [{ description: "Widget A", quantity: 2, unit_price: 500, amount: 1000 }],
  sa_alerts: [],
};

const CLASSIFIED_INVOICE = {
  ...PLAIN_INVOICE,
  doc_type: "DELIVERY_NOTE",
  doc_type_evidence: "Lieferschein",
};

async function openReviewConsole(page: Page, invoice: unknown) {
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route(`**/api/invoices/${INVOICE_ID}/pdf`, (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
  );
  await page.route(`**/api/invoices/${INVOICE_ID}`, (route) => route.fulfill(json(invoice)));

  await page.goto(`/invoices/review/${INVOICE_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("fields-panel")).toBeVisible({ timeout: FIRST_PAINT_TIMEOUT });
}

test.describe("FE Gap 378 — auditor console document type + evidence", () => {
  test.beforeEach(async ({ page }) => {
    await stubCommon(page);
  });

  test("shows neither row, nor the panel, when the record has no doc_type", async ({ page }) => {
    await openReviewConsole(page, PLAIN_INVOICE);

    await expect(page.getByTestId("doc-type-row")).toHaveCount(0);
    await expect(page.getByTestId("doc-type-evidence-row")).toHaveCount(0);
    // The panel's gate is unchanged for a record with no metadata of any kind:
    // adding doc_type to that condition must not make an empty panel appear.
    await expect(page.getByTestId("extracted-metadata-panel")).toHaveCount(0);
  });

  test("shows the type and the phrase it was classified from when present", async ({ page }) => {
    await openReviewConsole(page, CLASSIFIED_INVOICE);

    const panel = page.getByTestId("extracted-metadata-panel");
    await expect(panel).toBeAttached();

    const typeRow = page.getByTestId("doc-type-row");
    await expect(typeRow).toBeAttached();
    // Raw enum value here, not the ledger's humanised label: this console is
    // where a misclassification gets reported, so it shows what was stored.
    await expect(typeRow).toContainText("Document Type");
    await expect(typeRow).toContainText("DELIVERY_NOTE");

    const evidenceRow = page.getByTestId("doc-type-evidence-row");
    await expect(evidenceRow).toBeAttached();
    await expect(evidenceRow).toContainText("Type Evidence");
    await expect(evidenceRow).toContainText("Lieferschein");
  });

  test("shows the type alone when the classifier recorded no evidence phrase", async ({ page }) => {
    // The low-confidence fallback lands on OTHER with nothing to quote, so the
    // evidence row has to be independently conditional, not bundled with type.
    await openReviewConsole(page, {
      ...PLAIN_INVOICE,
      doc_type: "OTHER",
      doc_type_evidence: null,
    });

    await expect(page.getByTestId("doc-type-row")).toContainText("OTHER");
    await expect(page.getByTestId("doc-type-evidence-row")).toHaveCount(0);
  });
});
