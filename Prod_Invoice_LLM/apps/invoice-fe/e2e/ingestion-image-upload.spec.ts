// =============================================================================
// FILE: e2e/ingestion-image-upload.spec.ts
// FEATURE: FE Feature 19 — Image Upload Accept (FE half of BE Feature 28).
//
// TWO KINDS OF TEST, the split this repo already uses (see
// chat-attachment-contract.spec.ts): invoice-fe has @playwright/test and
// nothing else — no Jest, no vitest — so the "unit tests" the spec's
// Verification Plan asks for are pure-module assertions imported straight from
// lib/featureFlags.ts, run by the same runner as the browser passes below.
//
// WHAT IS LOAD-BEARING HERE:
//   1. The image suffixes are offered with NO flag (BE decision D1). A failed
//      or empty /api/config/features must still yield the image list, not
//      `.pdf` alone — that is the one behaviour a future "fail-closed" refactor
//      would most plausibly and most silently break.
//   2. The two DropZone guards and the on-screen copy all come off one array,
//      so the words cannot name a format the input rejects.
//   3. Feature 27's ENABLE_GENERIC_EXTRACTION path still composes rather than
//      being replaced — its list is unioned on top, never instead.
//
// Same stub-everything approach as the neighbouring specs: needs the Next dev
// server, no FastAPI backend, no DB, no seeded tenant.
// =============================================================================

import { test, expect, Page } from "@playwright/test";
import {
  GENERIC_EXTRACTION_EXTENSIONS,
  IMAGE_UPLOAD_EXTENSIONS,
  PDF_ONLY_EXTENSIONS,
  acceptedFormatsLabel,
  acceptedUploadExtensions,
  type FeatureFlags,
} from "@/lib/featureFlags";

const FIRST_PAINT_TIMEOUT = 90_000;
const EXPECTED_ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp";
const EXPECTED_LABEL = "PDF, PNG, JPG, TIFF, WEBP or BMP";

// SERIAL, deliberately. Every browser pass below drives `/ingestion` or
// `/trainer` on the Next DEV server, where the first request to a route pays a
// full on-demand compile. Run fully parallel, three workers compile two heavy
// routes at once and the slowest page loses: on 2026-09-04 that produced three
// failures ("element(s) not found" on the file input after 90s) that every one
// of the same tests passed in isolation. Serialising costs ~30s and removes a
// flake that would otherwise read as a product defect.
test.describe.configure({ mode: "serial", timeout: 120_000 });

// ---------------------------------------------------------------------------
// 19.1 / 19.3 — pure module assertions
// ---------------------------------------------------------------------------

test.describe("FE Feature 19 — acceptedUploadExtensions()", () => {
  test("offers the image list with the flag off, absent, or unfetchable", () => {
    // `{}` is a successful fetch with the flag off; `null` is "not resolved
    // yet"; `loadFeatureFlags()` also resolves to `{}` when the request fails.
    // All three must land on the same list, because BE Feature 28 converts
    // images unconditionally and there is no flag to be closed against.
    const cases: Array<FeatureFlags | null> = [{}, null, { ENABLE_GENERIC_EXTRACTION: false }];
    for (const flags of cases) {
      expect(acceptedUploadExtensions(flags)).toEqual([...IMAGE_UPLOAD_EXTENSIONS]);
    }
    expect(acceptedUploadExtensions({})).toContain(".pdf");
    expect(acceptedUploadExtensions({})).toContain(".png");
    expect(acceptedUploadExtensions({})).toContain(".webp");
    expect(acceptedUploadExtensions({})).toHaveLength(8);
  });

  test("unions Feature 27's list when ENABLE_GENERIC_EXTRACTION is on, de-duplicated, .pdf first", () => {
    const withFlag = acceptedUploadExtensions({ ENABLE_GENERIC_EXTRACTION: true });

    expect(withFlag[0]).toBe(".pdf");
    expect(new Set(withFlag).size).toBe(withFlag.length);

    // Composition, not replacement: every member of BOTH source lists survives.
    for (const ext of IMAGE_UPLOAD_EXTENSIONS) expect(withFlag).toContain(ext);
    for (const ext of GENERIC_EXTRACTION_EXTENSIONS) expect(withFlag).toContain(ext);

    // ...and the flag never narrows the always-on floor.
    expect(withFlag.length).toBeGreaterThanOrEqual(IMAGE_UPLOAD_EXTENSIONS.length);
  });

  test("the attribute string the inputs are built from", () => {
    expect(acceptedUploadExtensions({}).join(",")).toBe(EXPECTED_ACCEPT);
  });
});

test.describe("FE Feature 19 — acceptedFormatsLabel()", () => {
  test("names PDF alone for the PDF-only list", () => {
    expect(acceptedFormatsLabel([...PDF_ONLY_EXTENSIONS])).toBe("PDF");
  });

  test("folds the .jpeg/.tif aliases away for the full list", () => {
    // Not "PDF, PNG, JPG, JPEG, TIF, TIFF, WEBP or BMP" — a user does not need
    // to be told both spellings of the same format.
    expect(acceptedFormatsLabel([...IMAGE_UPLOAD_EXTENSIONS])).toBe(EXPECTED_LABEL);
  });

  test("degenerate inputs", () => {
    expect(acceptedFormatsLabel([])).toBe("");
    expect(acceptedFormatsLabel([".png", ".jpg"])).toBe("PNG or JPG");
  });
});

// ---------------------------------------------------------------------------
// Browser passes
// ---------------------------------------------------------------------------

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
 * Catch-all first — Playwright gives precedence to the most recently registered
 * handler. `/api/config/features` is deliberately left to the catch-all's `{}`
 * in most tests: that is the "flag off / nothing known" state, and the point of
 * Feature 19 is that the image list survives it.
 */
async function stubCommon(page: Page) {
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/auth/me", (route) => route.fulfill(json(ME)));
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({
        outbound_sender_email: null,
        billing_plan: "pro_combined",
        receive_invoices_enabled: true,
        send_invoices_enabled: false,
      })
    )
  );
}

/**
 * `/ingestion` is server-rendered, so the hidden input is attached several
 * seconds before React hydrates and binds `onChange`. Setting files in that
 * window is silently dropped. Same retry shape as feature27-doc-type.spec.ts —
 * a hydration race in the test, not a defect in the component.
 */
async function selectFileWhenHydrated(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
  reacted: () => Promise<void>
) {
  const input = page.locator(`input[type="file"][accept="${EXPECTED_ACCEPT}"]`).first();
  await expect(input).toBeAttached({ timeout: FIRST_PAINT_TIMEOUT });

  await expect(async () => {
    await input.setInputFiles(file);
    await reacted();
  }).toPass({ timeout: 60_000, intervals: [500, 1000, 2000] });
}

test.describe("FE Feature 19 — the ingestion drop zone", () => {
  test.beforeEach(async ({ page }) => {
    await stubCommon(page);
  });

  test("offers the image suffixes and says so, with the conversion hint", async ({ page }) => {
    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

    const input = page.locator('input[type="file"]').first();
    await expect(input).toBeAttached({ timeout: FIRST_PAINT_TIMEOUT });
    await expect(input).toHaveAttribute("accept", EXPECTED_ACCEPT);

    await expect(page.getByText(`Accepts ${EXPECTED_LABEL}. Max size 25MB.`)).toBeVisible();
    // Founder decision 2026-09-04 — this line is why a photo later shows up in
    // the ledger under a `.pdf` filename.
    await expect(
      page.getByText("Photos and scans are converted to PDF automatically.")
    ).toBeVisible();
    await expect(page.getByText("Drag & drop invoices here, or browse")).toBeVisible();
  });

  test("accepts a PNG and posts it to the upload proxy", async ({ page }) => {
    let uploadCalled = false;
    await page.route("**/api/invoices/upload", (route) => {
      uploadCalled = true;
      return route.fulfill(
        json({
          batch_id: "77777777-7777-7777-7777-777777777777",
          job_ids: ["88888888-8888-8888-8888-888888888888"],
        })
      );
    });
    await page.route("**/api/invoices/status/**", (route) =>
      route.fulfill(
        json({
          id: "88888888-8888-8888-8888-888888888888",
          // The backend rewrites the stored filename to `.pdf` (BE 28.3), so
          // the ledger row is a PDF even though a PNG was selected.
          status: "COMPLETED",
          alerts: [],
          vendor_name: "Hardware Depot Private Limited",
          grand_total: 1250.5,
          currency: "INR",
        })
      )
    );

    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

    const submit = page.getByRole("button", { name: "Submit Ingestion Batch" });
    await selectFileWhenHydrated(
      page,
      { name: "phone-photo.png", mimeType: "image/png", buffer: Buffer.from("not-really-a-png") },
      async () => {
        // Guard 1 (suffix check) let it through: it is queued, not rejected.
        await expect(submit).toBeEnabled({ timeout: 3_000 });
      }
    );
    await expect(
      page.getByText("Invalid file format.", { exact: false })
    ).toHaveCount(0);

    await submit.click();
    await expect(page.getByText("Ingestion Progress Queue")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });
    expect(uploadCalled).toBe(true);
  });

  test("still rejects a format outside the list, naming what is allowed", async ({ page }) => {
    await page.goto("/ingestion", { waitUntil: "domcontentloaded" });

    // `.gif` is not in either list — BE Feature 28's converter does not take
    // it, so widening the picker must not have widened it to everything.
    await selectFileWhenHydrated(
      page,
      { name: "animation.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") },
      async () => {
        await expect(
          page.getByText("Invalid file format.", { exact: false })
        ).toBeVisible({ timeout: 3_000 });
      }
    );

    // The message names the real list rather than "PDF only" — a user told the
    // wrong rule retries the wrong thing.
    await expect(page.getByText("Invalid file format.", { exact: false })).not.toHaveText(
      "Invalid file format. Only PDF documents are allowed."
    );
  });
});

test.describe("FE Feature 19 — the trainer upload input", () => {
  test("uses the same helper output as the drop zone", async ({ page }) => {
    await stubCommon(page);
    await page.route("**/api/trainer/vendors**", (route) => route.fulfill(json([])));

    await page.goto("/trainer", { waitUntil: "domcontentloaded" });

    const input = page.locator('input[type="file"]').first();
    await expect(input).toBeAttached({ timeout: FIRST_PAINT_TIMEOUT });
    await expect(input).toHaveAttribute("accept", EXPECTED_ACCEPT);
    await expect(page.getByText("Upload a sample invoice")).toBeVisible();
  });
});
