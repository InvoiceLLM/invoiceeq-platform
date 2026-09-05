import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 464 — the durable ingestion History screen.
 *
 * The claim under test is the founder's original symptom, inverted: a run that
 * produced only a `documents` row (Feature 27 decision E10 deletes the
 * placeholder `invoice` row) must render as a NORMAL, EXPLAINED line — never a
 * disappearance — and expanding it must fetch the full record on demand rather
 * than as part of the list.
 *
 * Also guarded: the sidebar swap is net zero ("Documents" gone, "History"
 * present), the source/direction/archived filters reach the backend as query
 * parameters, and Archive is offered under ONE label that never says "delete".
 *
 * Same approach as the existing specs here (see feature27-doc-type.spec.ts):
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

const DOC_RUN = "11111111-1111-1111-1111-111111111111";
const INV_RUN = "22222222-2222-2222-2222-222222222222";
const EMAIL_RUN = "email:33333333-3333-3333-3333-333333333333";

/** A run that produced only a `documents` row — the founder's symptom case. */
const DOCUMENT_ONLY_RUN = {
  run_id: DOC_RUN,
  source: "manual",
  flow_direction: "INBOUND",
  started_at: new Date().toISOString(),
  file_count: 1,
  loaded: 0,
  not_loaded: 1,
  rejected: 0,
  in_progress: 0,
  status: "NOT_LOADED",
  summary: "1 file: 1 not loaded",
  archived_at: null,
};

const INVOICE_RUN = {
  run_id: INV_RUN,
  source: "connector",
  flow_direction: "OUTBOUND",
  started_at: new Date(Date.now() - 3_600_000).toISOString(),
  file_count: 1,
  loaded: 1,
  not_loaded: 0,
  rejected: 0,
  in_progress: 0,
  status: "LOADED",
  summary: "1 file: 1 loaded",
  archived_at: null,
};

const REJECTED_EMAIL_RUN = {
  run_id: EMAIL_RUN,
  source: "email",
  flow_direction: null,
  started_at: new Date(Date.now() - 7_200_000).toISOString(),
  file_count: 1,
  loaded: 0,
  not_loaded: 0,
  rejected: 1,
  in_progress: 0,
  status: "REJECTED",
  summary: "Rejected — no invoice content",
  archived_at: null,
};

async function stubCommon(page: Page) {
  // Catch-all first: Playwright gives precedence to the most recently
  // registered handler, so anything registered after this one wins.
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

/** Records every /ingestion-history list URL the page requests. */
async function stubHistory(
  page: Page,
  items: unknown[],
  seen: string[] = []
): Promise<string[]> {
  await page.route("**/api/ingestion-history?**", (route) => {
    seen.push(route.request().url());
    return route.fulfill(
      json({ items, total: items.length, page: 1, page_size: 25 })
    );
  });
  return seen;
}

test.describe("FE Gap 464 — ingestion History screen", () => {
  test("a document-only run is an explained row, not a disappearance", async ({
    page,
  }) => {
    await stubCommon(page);
    await stubHistory(page, [DOCUMENT_ONLY_RUN, INVOICE_RUN, REJECTED_EMAIL_RUN]);

    await page.goto("/history", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });

    // FIRST_PAINT_TIMEOUT, not the 5s default: this is the first spec in the
    // file, so it pays for the dev server's first compile of /history.
    await expect(page.getByTestId("history-run")).toHaveCount(3, {
      timeout: FIRST_PAINT_TIMEOUT,
    });

    const docRow = page.locator(`[data-run-id="${DOC_RUN}"]`);
    await expect(docRow).toBeVisible();
    await expect(docRow.locator("[data-run-status]")).toHaveText("Not loaded");
    await expect(docRow).toContainText("1 file: 1 not loaded");
    // The empty state must NOT be what a user with a non-invoice sees.
    await expect(page.getByTestId("history-empty")).toHaveCount(0);

    // The rejected inbound email — Admin-console-only before this gap.
    await expect(page.locator(`[data-run-id="${EMAIL_RUN}"]`)).toContainText(
      "Rejected — no invoice content"
    );
  });

  test("the full record is fetched only when a row is expanded", async ({
    page,
  }) => {
    await stubCommon(page);
    await stubHistory(page, [DOCUMENT_ONLY_RUN]);

    let filesCalls = 0;
    await page.route("**/api/ingestion-history/*/files**", (route) => {
      filesCalls += 1;
      return route.fulfill(
        json({
          items: [
            {
              id: "file-1",
              kind: "document",
              file_name: "delivery-challan.pdf",
              outcome: "NOT_LOADED",
              outcome_label: "Not loaded — Delivery note",
              status: "EXTRACTED",
              doc_type: "DELIVERY_NOTE",
              created_at: new Date().toISOString(),
              record: {
                doc_type_evidence: "DELIVERY CHALLAN",
                party_name: "Bharat Steels Pvt Ltd",
                counterparty_name: "Novatech Industries",
                doc_number: "DC-2026-0912",
                items: [{ description: "MS Angle 50x50x6" }],
                doc_attributes: { direction: { value: "INBOUND" } },
              },
            },
          ],
        })
      );
    });

    await page.goto("/history", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("history-run")).toHaveCount(1, {
      timeout: FIRST_PAINT_TIMEOUT,
    });

    // Nothing heavy is fetched to render the list — this is the "it is a LOG,
    // not a data table" claim, asserted rather than described.
    expect(filesCalls).toBe(0);
    await expect(page.getByTestId("run-file")).toHaveCount(0);

    await page.locator(`[data-run-id="${DOC_RUN}"] button[aria-expanded]`).click();

    await expect(page.getByTestId("run-file")).toHaveCount(1);
    expect(filesCalls).toBe(1);
    await expect(page.getByTestId("run-file")).toContainText(
      "delivery-challan.pdf"
    );
    await expect(page.locator("[data-outcome='NOT_LOADED']")).toContainText(
      "Not loaded — Delivery note"
    );
    // Extracted fields, line items and doc attributes — the expensive half.
    await expect(page.getByTestId("run-file")).toContainText("DELIVERY CHALLAN");
    await expect(page.getByTestId("run-file")).toContainText("DC-2026-0912");
    await expect(page.getByTestId("run-file")).toContainText("1 line item");
    await expect(page.getByTestId("run-file")).toContainText("1 attribute");
  });

  test("source, direction and archived filters reach the backend", async ({
    page,
  }) => {
    await stubCommon(page);
    const seen: string[] = [];
    await stubHistory(page, [DOCUMENT_ONLY_RUN], seen);

    await page.goto("/history", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("history-run")).toHaveCount(1, {
      timeout: FIRST_PAINT_TIMEOUT,
    });

    await page.getByTestId("history-filter-source-email").click();
    await expect
      .poll(() => seen.some((u) => u.includes("trigger=email")))
      .toBe(true);

    await page.getByTestId("history-filter-direction-OUTBOUND").click();
    await expect
      .poll(() => seen.some((u) => u.includes("flow_direction=OUTBOUND")))
      .toBe(true);

    await page.getByTestId("history-filter-archived").click();
    await expect
      .poll(() => seen.some((u) => u.includes("archived=true")))
      .toBe(true);
    // The archived view renames the panel rather than mixing archived rows in
    // with live ones.
    await expect(page.getByText("Archived", { exact: false }).first()).toBeVisible();
  });

  test("archive is the only word offered, and it never says delete", async ({
    page,
  }) => {
    await stubCommon(page);
    await stubHistory(page, [DOCUMENT_ONLY_RUN]);
    let archiveCalls = 0;
    await page.route("**/api/ingestion-history/*/archive**", (route) => {
      archiveCalls += 1;
      return route.fulfill(json({ archived: 1 }));
    });

    await page.goto("/history", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("history-run")).toHaveCount(1, {
      timeout: FIRST_PAINT_TIMEOUT,
    });

    const panel = page.locator("#ingestion-history");
    await expect(panel).toContainText("Archive all");
    await expect(panel).toContainText(
      "Invoices and documents are never deleted here"
    );
    // The founder's ruling: one label, and never a second word for the same
    // behaviour. "Hide" and "Delete" must not appear as actions on this screen.
    await expect(panel.getByRole("button", { name: /delete/i })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: /^hide/i })).toHaveCount(0);

    await page.getByTestId("history-archive").click();
    await expect.poll(() => archiveCalls).toBe(1);
  });

  test("the sidebar swap is net zero: Documents out, History in", async ({
    page,
  }) => {
    await stubCommon(page);
    await stubHistory(page, []);

    await page.goto("/history", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("history-empty")).toBeVisible({
      timeout: FIRST_PAINT_TIMEOUT,
    });

    const sidebar = page.locator("nav").first();
    await expect(sidebar.getByRole("link", { name: "History" })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Documents" })).toHaveCount(0);
  });
});
