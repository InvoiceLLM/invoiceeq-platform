import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 279 — Audit Review Console queue navigation.
 *
 * Gap 272 added Previous/Next to this screen but scoped the queue to
 * `GET /invoices?status=AUDIT_REQUIRED`. Opening any other invoice therefore
 * left both controls disabled and the position counter hidden — visually
 * identical to having no navigation at all, which is how the screen got
 * re-reported as "you still have to go back and pick the next one".
 *
 * Every /api/** call is stubbed (same approach as audit-review-console.spec.ts),
 * so this needs the Next dev server but no FastAPI backend, DB or seeded tenant.
 *
 * The stubs are deliberately self-contained rather than shared with
 * audit-review-console.spec.ts: that file's helper stubs `**\/api/invoices?**`
 * to an empty list, which is the exact call this spec needs to return real
 * rows, and a shared helper that both files kept editing in opposite directions
 * would be worse than a little duplication.
 */

test.describe.configure({ timeout: 120_000 });

const FIRST_PAINT_TIMEOUT = 90_000;

const ID_A = "aaaaaaaa-0000-0000-0000-000000000001";
const ID_B = "bbbbbbbb-0000-0000-0000-000000000002";
const ID_C = "cccccccc-0000-0000-0000-000000000003";
const ID_ORPHAN = "dddddddd-0000-0000-0000-000000000004";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

function invoice(id: string, status: string) {
  return {
    id,
    status,
    vendor_name: "Hardware Depot",
    invoice_number: `INV-${id.slice(0, 4)}`,
    invoice_date: "2026-01-15",
    due_date: "2026-02-15",
    grand_total: 1250.5,
    tax_amount: 100.5,
    flow_direction: "INBOUND",
    field_confidence: {},
    coordinates: [],
    items: [],
    sa_alerts: [],
  };
}

/**
 * @param queue  ids returned for the queue fetch, in order
 * @param status the status every invoice here carries — this is what the page
 *               derives the queue from when no `?queue=` is supplied
 */
async function stub(page: Page, queue: string[], status: string) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill(
      json({ role: "Admin", tenant_id: "t1", user_id: "u1", billing_plan: "free" })
    )
  );
  await page.route("**/api/settings/service-flow", (route) =>
    route.fulfill(
      json({ receive_enabled: true, send_enabled: false, outbound_sender_email: null, billing_plan: "free" })
    )
  );
  await page.route("**/api/outbound-dashboard/invoices**", (route) =>
    route.fulfill({ ...json([]), headers: { "x-total-count": "0" } })
  );
  await page.route("**/api/invoices/*/pdf", (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: "" })
  );

  // The queue fetch. Also serves the notification bell's own count calls —
  // both go through `/api/invoices?...`, and returning the queue to both is
  // harmless here since nothing in this spec asserts on the bell.
  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({
      ...json(queue.map((id) => ({ id }))),
      headers: { "x-total-count": String(queue.length) },
    })
  );

  // Invoice detail — matched per id so navigation lands on a real payload.
  for (const id of [...queue, ID_ORPHAN]) {
    await page.route(`**/api/invoices/${id}`, (route) =>
      route.fulfill(json(invoice(id, status)))
    );
  }
}

const nextBtn = (page: Page) => page.getByRole("button", { name: "Next invoice in this queue" });
const prevBtn = (page: Page) => page.getByRole("button", { name: "Previous invoice in this queue" });

async function open(page: Page, id: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/invoices/review/${id}`, { waitUntil: "domcontentloaded" });
  await expect(nextBtn(page)).toBeVisible({ timeout: FIRST_PAINT_TIMEOUT });
}

// ---------------------------------------------------------------------------

test("COMPLETED invoice gets working queue navigation (the Gap 279 regression)", async ({ page }) => {
  // Before the fix the queue was hardcoded to AUDIT_REQUIRED, so a COMPLETED
  // invoice produced auditQueueIndex === -1: both buttons disabled, counter
  // hidden. This is the exact reported case.
  await stub(page, [ID_A, ID_B, ID_C], "COMPLETED");
  await open(page, ID_B);

  await expect(page.getByText("2 of 3")).toBeVisible();
  await expect(nextBtn(page)).toBeEnabled();
  await expect(prevBtn(page)).toBeEnabled();
});

test("Next advances to the following invoice in the queue", async ({ page }) => {
  await stub(page, [ID_A, ID_B, ID_C], "COMPLETED");
  await open(page, ID_A);

  await expect(page.getByText("1 of 3")).toBeVisible();
  await expect(prevBtn(page)).toBeDisabled();

  await nextBtn(page).click();
  await expect(page).toHaveURL(new RegExp(ID_B));
});

test("ends of the queue disable the correct control", async ({ page }) => {
  await stub(page, [ID_A, ID_B, ID_C], "AUDIT_REQUIRED");

  await open(page, ID_A);
  await expect(prevBtn(page)).toBeDisabled();
  await expect(nextBtn(page)).toBeEnabled();

  await open(page, ID_C);
  await expect(nextBtn(page)).toBeDisabled();
  await expect(prevBtn(page)).toBeEnabled();
});

test("an invoice outside the queue says so instead of showing dead buttons", async ({ page }) => {
  // Reached from a chat citation or the notification bell: genuinely not part
  // of any queue. Gap 279's point is that this must be distinguishable from
  // the broken state, not identical to it.
  await stub(page, [ID_A, ID_B], "COMPLETED");
  await open(page, ID_ORPHAN);

  await expect(page.getByText("not in queue")).toBeVisible();
  await expect(nextBtn(page)).toBeDisabled();
  await expect(prevBtn(page)).toBeDisabled();
});

test("j steps forward, k steps back, and neither fires while typing", async ({ page }) => {
  await stub(page, [ID_A, ID_B, ID_C], "AUDIT_REQUIRED");
  await open(page, ID_B);

  // Focus has to be in the parent document for a window-level keydown to be
  // seen at all. This is not test scaffolding around a broken feature — the
  // screen embeds the PDF in an <iframe>, and while that iframe holds focus
  // its keystrokes go to the embedded document and never reach us. Clicking
  // the page body first mirrors what a user does before reaching for a
  // shortcut; the limitation itself is recorded on the handler in page.tsx.
  await page.locator("body").click({ position: { x: 5, y: 5 } });

  await page.keyboard.press("j");
  await expect(page).toHaveURL(new RegExp(ID_C));

  await page.keyboard.press("k");
  await expect(page).toHaveURL(new RegExp(ID_B));

  // The guard that matters: this screen is full of editable correction fields,
  // and an unguarded handler would navigate away mid-edit and discard the
  // user's uncommitted correction.
  const field = page.locator("input:visible").first();
  if (await field.count()) {
    await field.click();
    await field.type("j");
    await expect(page).toHaveURL(new RegExp(ID_B));
  }
});

test("an explicit ?queue= overrides the invoice's own status and survives navigation", async ({ page }) => {
  await stub(page, [ID_A, ID_B, ID_C], "COMPLETED");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/invoices/review/${ID_A}?queue=AUDIT_REQUIRED`, {
    waitUntil: "domcontentloaded",
  });
  await expect(nextBtn(page)).toBeVisible({ timeout: FIRST_PAINT_TIMEOUT });

  await nextBtn(page).click();
  await expect(page).toHaveURL(new RegExp(ID_B));
  // Dropping the param on the first hop would silently re-point the queue at
  // the next invoice's own status.
  await expect(page).toHaveURL(/queue=AUDIT_REQUIRED/);
});
