// =============================================================================
// FILE: e2e/chat-insights.spec.ts
// FEATURE: FE Feature 21 tasks 21.5 / 21.9 — the intelligence bubble in a real
//          browser, on /chat.
//
// STUBBED, like every other spec in this directory: `page.route()` answers
// `/api/**`, so this needs the Next dev server and neither FastAPI, Postgres,
// Redis nor `ENABLE_ATTACHMENT_INSIGHTS`. The fixtures below are the shapes the
// backend actually emits — `services/attachment_insights.py::build_insight_block()`
// for the block, `routers/chat.py::InsightOut` for the lifecycle rows — not the
// spec's sketch of them.
//
// WHAT THIS PROVES: the §8.3 anatomy renders under the assistant turn, the three
// approved actions are the only actions, Add a note and Dismiss hit
// `/chat/insights/{id}/transition` with the right body, Discuss seeds the
// composer WITHOUT sending, and a turn without `insights` grows nothing.
//
// WHAT IT DELIBERATELY DOES NOT DO: attach a real PDF and wait for a real
// insight job. That path needs a backend, and 21.7's SSE leg cannot fire at all
// today — the event is published on a job id the browser is never given
// (FE Gap 474). The redraw is asserted here the only honest way available: by
// re-serving the session with a version-2 block and reloading, which exercises
// the same render path the SSE handler drives.
// =============================================================================

import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SESSION_ID = "5f1c9d20-1111-4c2a-9a3b-0000000000e2";
const MESSAGE_ID = "5f1c9d20-2222-4c2a-9a3b-0000000000e2";
const ATTACHMENT_ID = "5f1c9d20-3333-4c2a-9a3b-0000000000e2";
const INSIGHT_ID = "5f1c9d20-4444-4c2a-9a3b-0000000000e2";

const EVIDENCE_DIR = path.resolve(__dirname, "../docs/test_evidence/fe21_business_intelligence");

/** `build_insight_block()` output for a purchase order with four findings. */
function insightBlock(stage: "sync" | "async" = "sync") {
  return {
    stage,
    doc_type: "PURCHASE_ORDER",
    doc_type_label: "purchase order",
    attachment_id: ATTACHMENT_ID,
    currency: "INR",
    verdict:
      stage === "sync"
        ? "Check the Shree Packaging invoice — it bills more than this purchase order agreed."
        : "Two invoices bill more than this purchase order agreed, by ₹27,300 in total.",
    verdict_source: stage === "sync" ? "template" : "model",
    generated_at: stage === "sync" ? "2026-09-08T10:15:00Z" : "2026-09-08T10:16:30Z",
    cards: [],
    figures: {},
    actions: [
      { action: "note", label: "Add a note", status: "ACTED", outcome: "note" },
      { action: "discuss", label: "Discuss", endpoint: "discuss" },
      { action: "dismiss", label: "Dismiss", status: "DISMISSED", outcome: "dismissed" },
    ],
    checks_not_run: [
      { card: "bank_match", reason: "no bank statement on file" },
      { card: "compliance", reason: "the tax number is missing from this document" },
    ],
    findings: [
      {
        finding_key: "agreed_vs_billed:INV-1001",
        card: "agreed_vs_billed",
        title: "INV-1001 bills more than this purchase order agreed",
        impact_amount: 23200,
        currency: "INR",
        confidence: "high",
        confidence_reason: "both documents state a total",
        evidence: { invoice_number: "INV-1001", agreed: 100000, billed: 123200 },
      },
      {
        finding_key: "duplicate_billing:INV-1002",
        card: "duplicate_billing",
        title: "INV-1002 repeats a line already billed on INV-1001",
        impact_amount: 4100,
        currency: "INR",
        confidence: "med",
        confidence_reason: "the descriptions match but the quantities differ",
        evidence: { invoice_number: "INV-1002" },
      },
      {
        finding_key: "delivery_vs_order:INV-1003",
        card: "delivery_vs_order",
        title: "INV-1003 bills 40 units but 30 were delivered",
        impact_amount: null,
        confidence: "low",
        confidence_reason: "the delivery note states no unit",
        evidence: { invoice_number: "INV-1003", direction: "short_delivery" },
      },
      {
        finding_key: "price_drift:INV-1004",
        card: "price_drift",
        title: "INV-1004 charges more per unit than the last order",
        impact_amount: 900,
        currency: "INR",
        confidence: "med",
        confidence_reason: "one earlier order to compare against",
        evidence: { invoice_number: "INV-1004" },
      },
    ],
  };
}

/** `routers/chat.py::InsightOut`. */
const insightRow = {
  id: INSIGHT_ID,
  attachment_id: ATTACHMENT_ID,
  session_id: SESSION_ID,
  doc_type: "PURCHASE_ORDER",
  card: "agreed_vs_billed",
  finding_key: "agreed_vs_billed:INV-1001",
  title: "INV-1001 bills more than this purchase order agreed",
  impact_amount: 23200,
  currency: "INR",
  confidence: "high",
  confidence_reason: "both documents state a total",
  evidence: { invoice_number: "INV-1001" },
  status: "OPEN",
  is_open: true,
  outcome: null,
  note: null,
  snoozed_until: null,
  created_at: "2026-09-08T10:15:00Z",
  updated_at: "2026-09-08T10:15:00Z",
};

function messages(stage: "sync" | "async" = "sync") {
  return [
    {
      id: "5f1c9d20-0000-4c2a-9a3b-0000000000e2",
      session_id: SESSION_ID,
      role: "user",
      content: "Here is the Shree Packaging purchase order.",
      created_at: "2026-09-08T10:14:00Z",
      status: "completed",
    },
    {
      id: MESSAGE_ID,
      session_id: SESSION_ID,
      role: "assistant",
      content: insightBlock(stage).verdict,
      created_at: "2026-09-08T10:15:00Z",
      status: "completed",
      insights: insightBlock(stage),
    },
    {
      // The control: an ordinary turn with no `insights` key at all.
      id: "5f1c9d20-5555-4c2a-9a3b-0000000000e2",
      session_id: SESSION_ID,
      role: "assistant",
      content: "You have **3** overdue invoices.",
      created_at: "2026-09-08T10:17:00Z",
      status: "completed",
    },
  ];
}

const transitions: Array<{ url: string; body: any }> = [];

async function openStubbedChat(page: Page, stage: "sync" | "async" = "sync") {
  // `next dev` compiles /chat on first request; that build cost is not a product
  // defect, so it gets time rather than a retry (the neighbouring specs' rule).
  test.setTimeout(150_000);
  transitions.length = 0;

  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        tenant_name: "E2E Workspace",
        user_id: "user_e2e",
        role: "Admin",
        billing_plan: "active",
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
        send_invoices_enabled: false,
        outbound_sender_email: null,
        billing_plan: "free",
      }),
    })
  );
  await page.route("**/api/chat/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: SESSION_ID,
          tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
          user_id: "user_e2e",
          title: "Shree Packaging PO",
          message_count: 3,
          created_at: "2026-09-08T10:00:00Z",
          updated_at: "2026-09-08T10:17:00Z",
        },
      ]),
    })
  );
  await page.route(`**/api/chat/sessions/${SESSION_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(messages(stage)),
    })
  );

  // The lifecycle rows the bubble joins its findings to (FE Gap 472).
  await page.route("**/api/chat/insights?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([insightRow]),
    })
  );
  await page.route(`**/api/chat/insights/${INSIGHT_ID}/transition`, async (route) => {
    transitions.push({
      url: route.request().url(),
      body: JSON.parse(route.request().postData() || "{}"),
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...insightRow, status: "ACTED", is_open: false, outcome: "note" }),
    });
  });
  await page.route(`**/api/chat/insights/${INSIGHT_ID}/discuss`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        insight_id: INSIGHT_ID,
        attachment_id: ATTACHMENT_ID,
        seed_text:
          "About this finding (INR 23,200.00): INV-1001 bills more than this purchase order agreed — what should I do?",
      }),
    })
  );

  await page.goto("/chat");
  await page.locator(`#chat-session-${SESSION_ID}`).click();
  await expect(page.locator('[data-testid="insight-bubble"]')).toBeVisible();
}

test.describe("FE Feature 21 — the intelligence bubble on /chat", () => {
  test("renders the §8.3 anatomy and saves the screenshot evidence", async ({ page }) => {
    await openStubbedChat(page);

    const bubble = page.locator('[data-testid="insight-bubble"]');
    await expect(bubble).toHaveAttribute("data-stage", "sync");
    await expect(bubble.locator('[data-testid="insight-verdict"]')).toContainText(
      "bills more than this purchase order agreed"
    );

    // Up to three findings, the fourth collapsed.
    await expect(bubble.locator('[data-testid="insight-finding"]')).toHaveCount(3);
    await expect(bubble.locator('[data-testid="insight-more-findings"]')).toContainText(
      "1 more finding"
    );

    // Currency impact, in the tenant's currency, with tabular numerals.
    const impacts = bubble.locator('[data-testid="insight-finding-impact"]');
    await expect(impacts).toHaveCount(2); // the third finding states no amount
    await expect(impacts.first()).toContainText("23,200");

    // Confidence chips carry their reason.
    const chips = bubble.locator('[data-testid="insight-confidence-chip"]');
    await expect(chips.first()).toHaveAttribute("data-confidence", "high");
    await expect(chips.first()).toContainText("both documents state a total");

    // Evidence is plain text (founder 2026-09-08), never a link.
    await expect(bubble.locator('[data-testid="insight-evidence"]').first()).toHaveText("INV-1001");
    await expect(bubble.locator('[data-testid="insight-evidence-link"]')).toHaveCount(0);

    // The "not checked" line names both skipped checks and why.
    await expect(bubble.locator('[data-testid="insight-checks-not-run"]')).toContainText(
      "no bank statement on file"
    );

    // Expanding shows the fourth.
    await bubble.locator('[data-testid="insight-more-findings"]').click();
    await expect(bubble.locator('[data-testid="insight-finding"]')).toHaveCount(4);

    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    await bubble.screenshot({ path: path.join(EVIDENCE_DIR, "insight-bubble.png") });
    await page.screenshot({
      path: path.join(EVIDENCE_DIR, "chat-with-insight-bubble.png"),
      fullPage: true,
    });
  });

  test("information only — three actions, no pin and nothing that changes an invoice", async ({
    page,
  }) => {
    await openStubbedChat(page);
    const bubble = page.locator('[data-testid="insight-bubble"]');

    await expect(bubble.locator('[data-testid="insight-action-discuss"]')).toBeVisible();
    await expect(bubble.locator('[data-testid="insight-action-note"]')).toBeVisible();
    await expect(bubble.locator('[data-testid="insight-action-dismiss"]')).toBeVisible();

    const text = ((await bubble.textContent()) || "").toLowerCase();
    for (const banned of ["pin", "keep this", "hold", "dispute", "mark paid", "tier", "delta"]) {
      expect(text).not.toContain(banned);
    }
  });

  test("Add a note records ACTED + note and never sends a chat turn", async ({ page }) => {
    await openStubbedChat(page);
    const bubble = page.locator('[data-testid="insight-bubble"]');

    await bubble.locator('[data-testid="insight-action-note"]').click();
    await bubble.locator('[data-testid="insight-note-input"]').fill("Called the supplier");
    await bubble.locator('[data-testid="insight-note-save"]').click();

    await expect(bubble.locator('[data-testid="insight-outcome"]')).toBeVisible();
    expect(transitions).toHaveLength(1);
    expect(transitions[0].body).toEqual({
      status: "ACTED",
      outcome: "note",
      note: "Called the supplier",
    });
  });

  test("Dismiss records DISMISSED + dismissed", async ({ page }) => {
    await openStubbedChat(page);
    const bubble = page.locator('[data-testid="insight-bubble"]');

    await bubble.locator('[data-testid="insight-action-dismiss"]').click();

    await expect(bubble.locator('[data-testid="insight-outcome"]')).toBeVisible();
    expect(transitions).toHaveLength(1);
    expect(transitions[0].body).toEqual({ status: "DISMISSED", outcome: "dismissed" });
  });

  test("Discuss fills the composer and leaves the sending to the user", async ({ page }) => {
    await openStubbedChat(page);

    // If Discuss ever sent, it would POST here. Failing the test is the point.
    let sent = false;
    await page.route(`**/api/chat/sessions/${SESSION_ID}/message`, (route) => {
      sent = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.locator('[data-testid="insight-action-discuss"]').click();

    const composer = page.locator("#chat-input-textarea");
    await expect(composer).toHaveValue(/what should I do\?/);
    await expect(composer).toBeFocused();
    expect(sent).toBe(false);
  });

  test("the async stage's redraw shows the updated verdict in the same bubble", async ({
    page,
  }) => {
    // The SSE leg cannot fire (FE Gap 474), so the render path is exercised by
    // serving the version-2 block — which is what the handler's refetch does.
    await openStubbedChat(page, "async");
    const bubble = page.locator('[data-testid="insight-bubble"]');

    await expect(bubble).toHaveAttribute("data-stage", "async");
    await expect(bubble.locator('[data-testid="insight-verdict"]')).toContainText("27,300");
    // Still ONE bubble: the async stage replaces in place, never argues with a
    // second turn.
    await expect(page.locator('[data-testid="insight-bubble"]')).toHaveCount(1);
  });

  test("a turn without insights grows nothing", async ({ page }) => {
    await openStubbedChat(page);
    // Three turns are served; only the middle one carries a block.
    await expect(page.locator('[data-testid="insight-bubble"]')).toHaveCount(1);
    await expect(page.getByText("You have 3 overdue invoices.")).toBeVisible();
  });
});
