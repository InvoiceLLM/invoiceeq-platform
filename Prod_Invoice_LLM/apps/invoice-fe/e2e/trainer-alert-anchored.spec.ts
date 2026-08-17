import { test, expect, Page } from "@playwright/test";

/**
 * Feature 14 (FE) verification — the alert-anchored Trainer.
 *
 * Covers the four structural properties the redesign is *for*, rather than
 * incidental rendering:
 *
 *   1. The route gates on `can_train`, not just on billing plan (FE Gap 232).
 *   2. A correction is anchored to a real alert on a real invoice, and the
 *      form offered depends on that alert type's registry `correctionForm` —
 *      including offering **no** numeric form for a type that has no knob.
 *   3. Nothing saves without the preview gate: opening the commit dialog runs
 *      `/preview`, and the confirm sends its token.
 *   4. A `not_computable` impact renders as an explicit explanation, never as a
 *      zero.
 *
 * Stub-everything, same as the rest of `e2e/` — needs the Next dev server, no
 * FastAPI backend and no DB.
 */

/**
 * Playwright's default 30s per-test timeout is not enough for the first tests in
 * a run: `playwright.config.ts` starts `next dev`, which JIT-compiles /trainer
 * on first navigation, and with `fullyParallel: true` several workers hit that
 * compile at once. Observed directly — the whole file passes in ~4s per test
 * once compiled, and only the ones racing the initial compile time out. Raised
 * here rather than globally so this stays a statement about this file's dev-server
 * dependency, not a blanket loosening of every spec's timeout.
 */
test.describe.configure({ timeout: 90_000 });

const INVOICE_ID = "11111111-2222-3333-4444-555555555555";
const SESSION_ID = "sess-e2e-anchored";

const TOLERANCE_ALERT = {
  id: "alert-0",
  type: "tax_mismatch",
  label: "Tax mismatch",
  message: "Tax of 18.00 does not reconcile with the subtotal.",
  field: "tax_amount",
  severity: "warning",
  correctionForm: "tolerance",
  toleranceOverridable: true,
  thresholdOverridable: false,
  notCorrectableReason: "",
  known: true,
};

const SOURCE_TEXT_ALERT = {
  id: "alert-1",
  type: "total_not_verified_in_source",
  label: "Total not verified in source",
  message: "The grand total could not be found verbatim in the document text.",
  field: "grand_total",
  severity: "warning",
  // The registry reports this type as relabel-only: it asks a verbatim-presence
  // question with no numeric band to widen.
  correctionForm: "severity_message",
  toleranceOverridable: false,
  thresholdOverridable: false,
  notCorrectableReason:
    "This check asks whether the figure appears verbatim in the document text — there is no tolerance band to widen.",
  known: true,
};

const SESSION = {
  sessionId: SESSION_ID,
  scope: "existing_vendor",
  vendorName: "Northwind Freight",
  fileName: "northwind.pdf",
  pdfUrl: `/api/invoices/${INVOICE_ID}/pdf`,
  createdAt: "2026-08-12T10:00:00Z",
  variables: [
    {
      id: "v-tax",
      key: "tax_amount",
      label: "Tax Amount",
      value: "18.00",
      confidence: 0.91,
    },
  ],
  activeRules: [],
  activeRulesDetailed: [],
  chatHistory: [],
  sessionMode: "rule_creation",
  invoiceId: INVOICE_ID,
  flowDirection: "INBOUND",
  alerts: [TOLERANCE_ALERT, SOURCE_TEXT_ALERT],
};

async function stubIdentity(page: Page, canTrain: boolean) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        tenant_name: "E2E Workspace",
        user_id: "user_e2e",
        billing_plan: "active",
        role: "Admin",
        can_train: canTrain,
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
}

async function stubSession(page: Page) {
  await page.route("**/api/trainer/vendors**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "v1",
          name: "Northwind Freight",
          invoiceCount: 4,
          sampleInvoiceId: INVOICE_ID,
          sampleFileName: "northwind.pdf",
          samplePdfUrl: `/api/invoices/${INVOICE_ID}/pdf`,
        },
      ]),
    })
  );

  await page.route("**/api/invoices?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: INVOICE_ID,
          invoice_number: "INV-2001",
          vendor_name: "Northwind Freight",
          status: "AUDIT_REQUIRED",
          grand_total: 1240.5,
          currency: "USD",
          created_at: "2026-08-01T09:00:00Z",
          invoice_date: "2026-07-28",
          sa_alerts: [TOLERANCE_ALERT, SOURCE_TEXT_ALERT],
        },
      ]),
    })
  );

  await page.route("**/api/trainer/sessions/from-invoice**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SESSION),
    })
  );

  // The PDF panel renders an <iframe> at this URL; fulfil it so the dev server
  // isn't asked for a backend-backed binary that doesn't exist here.
  await page.route("**/api/invoices/*/pdf", (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-1.4 stub" })
  );
}

async function gotoTrainer(page: Page) {
  for (let attempt = 0; ; attempt++) {
    try {
      await page.goto("/trainer", { waitUntil: "domcontentloaded", timeout: 60_000 });
      break;
    } catch (err) {
      if (attempt >= 2) throw err;
    }
  }
}

async function openSession(page: Page) {
  await gotoTrainer(page);
  await expect(page.getByTestId("trainer-invoice-picker")).toBeVisible({ timeout: 60_000 });
  await page.getByText("INV-2001").click();
  await expect(page.getByTestId("trainer-alert-list")).toBeVisible();
}

test.describe("Feature 14 — alert-anchored Trainer", () => {
  test("FE Gap 232: a user without can_train never sees the sandbox", async ({ page }) => {
    await stubIdentity(page, false);
    await stubSession(page);

    await gotoTrainer(page);

    // The permission state, not the workspace — and not the billing upgrade
    // prompt either, since the plan is fine.
    await expect(page.getByText("Training Permission Required")).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByTestId("trainer-entry-panel")).toHaveCount(0);
    await expect(page.getByText("Upgrade Required")).toHaveCount(0);
  });

  test("a tolerance-overridable alert offers the numeric tolerance form", async ({ page }) => {
    await stubIdentity(page, true);
    await stubSession(page);
    await openSession(page);

    await page.getByTestId("trainer-alert-row").first().getByText("Train on this").click();
    await expect(page.getByTestId("alert-correction-modal")).toBeVisible();

    await page.getByTestId("correction-option-unnecessary").click();
    await expect(page.getByTestId("tolerance-form")).toBeVisible();
    await expect(page.getByTestId("not-tunable-explainer")).toHaveCount(0);
  });

  test("a source-text alert offers an explanation instead of a tolerance form", async ({
    page,
  }) => {
    await stubIdentity(page, true);
    await stubSession(page);
    await openSession(page);

    // The second row is `total_not_verified_in_source` — relabel-only.
    await page.getByTestId("trainer-alert-row").nth(1).getByText("Train on this").click();
    await page.getByTestId("correction-option-unnecessary").click();

    // No numeric control is rendered; the registry's reason is shown instead.
    await expect(page.getByTestId("not-tunable-explainer")).toBeVisible();
    await expect(page.getByTestId("tolerance-form")).toHaveCount(0);
    await expect(page.getByTestId("threshold-form")).toHaveCount(0);
    await expect(page.getByTestId("not-tunable-explainer")).toContainText(
      "no tolerance band to widen"
    );
  });

  test("commit runs the preview gate first and sends its token", async ({ page }) => {
    await stubIdentity(page, true);
    await stubSession(page);

    let previewCalled = false;
    let commitBody: any = null;

    await page.route("**/api/trainer/sessions/*/preview", async (route) => {
      previewCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          previewToken: "tok-abc123",
          scope: "vendor",
          vendorName: "Northwind Freight",
          newRules: [
            {
              kind: "tolerance_override",
              field: "tax_amount",
              condition: "abs_tol=5.0;rel_tol=0.01",
              scope: "vendor",
              sourceAlertType: "tax_mismatch",
              origin: "trainer_alert_correction",
              text: "Treat a 'tax_mismatch' difference as acceptable within 5.00 or 1%.",
              params: { abs_tol: 5.0, rel_tol: 0.01 },
            },
          ],
          impact: {
            kind: "exact",
            summary: "Replayed against 12 stored invoice(s): 3 alert(s) would no longer fire.",
            rules: [],
            invoicesExamined: 12,
            alertsRemoved: 3,
            alertsAdded: 0,
            invoicesAffected: 3,
            alertsRelabelled: null,
            sample: [
              {
                invoiceId: INVOICE_ID,
                invoiceNumber: "INV-2001",
                vendorName: "Northwind Freight",
                alertsRemoved: ["tax_mismatch"],
                alertsAdded: [],
              },
            ],
            notComputable: [],
          },
        }),
      });
    });

    await page.route("**/api/trainer/sessions/*/commit", async (route) => {
      commitBody = JSON.parse(route.request().postData() || "{}");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          scope: "existing_vendor",
          vendor_name: "Northwind Freight",
          version: 4,
          rules: { constraints: [] },
          reaudit_queued: true,
        }),
      });
    });

    await openSession(page);
    await page.getByTestId("trainer-review-commit").click();

    await expect(page.getByTestId("commit-preview-modal")).toBeVisible();
    expect(previewCalled).toBe(true);

    // The structured interpretation and the real replay figures are both shown.
    await expect(page.getByTestId("preview-impact")).toContainText("12");
    await expect(page.getByTestId("impact-sample")).toContainText("INV-2001");

    await page.getByTestId("confirm-commit").click();
    await expect
      .poll(() => commitBody?.preview_token, { timeout: 15_000 })
      .toBe("tok-abc123");
  });

  test("a text rule's impact is reported as not computable, never as zero", async ({ page }) => {
    await stubIdentity(page, true);
    await stubSession(page);

    await page.route("**/api/trainer/sessions/*/preview", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          previewToken: "tok-text",
          scope: "vendor",
          vendorName: "Northwind Freight",
          newRules: [
            {
              kind: "extraction",
              field: "tax_amount",
              condition: "expected_alert=tax_mismatch",
              scope: "vendor",
              sourceAlertType: "tax_mismatch",
              origin: "trainer_missed_alert",
              text: "Read this vendor's tax as exclusive of freight.",
              params: {},
            },
          ],
          impact: {
            kind: "not_computable",
            summary:
              "This rule changes how the model reads invoices. Its historical effect can't be computed without re-processing every past invoice, so no count is shown.",
            rules: [],
            invoicesExamined: 0,
            alertsRemoved: null,
            alertsAdded: null,
            invoicesAffected: null,
            alertsRelabelled: null,
            sample: [],
            notComputable: [{ reason: "Free-text extraction rule", appliesTo: "extraction rules" }],
          },
        }),
      })
    );

    await openSession(page);
    await page.getByTestId("trainer-review-commit").click();

    const notComputable = page.getByTestId("impact-not-computable");
    await expect(notComputable).toBeVisible();
    await expect(notComputable).toContainText("can't be computed");
    // The honest-empty-state guarantee: no fabricated zero anywhere in the block.
    await expect(page.getByTestId("impact-sample")).toHaveCount(0);
  });
});
