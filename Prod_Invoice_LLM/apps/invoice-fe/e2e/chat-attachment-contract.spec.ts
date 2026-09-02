// =============================================================================
// FILE: e2e/chat-attachment-contract.spec.ts
// FEATURE: BE Feature 26 Part 2, task H11 (§P2.6.4–§P2.6.5) — MessageBubble's
//          rendering of the attached-document answer contract, DocumentEvidence,
//          and the contract types on ChatMessage.
//
// TWO KINDS OF TEST HERE, and the split is deliberate:
//
//   1. Pure-module assertions on lib/chatAttachments.ts — the same shape H10's
//      chat-attachment-guards.spec.ts uses, for the same reason: invoice-fe has
//      @playwright/test and nothing else (no Jest, no vitest, no RTL), and
//      Playwright's babel transform rewrites JSX in a spec and in any .tsx it
//      imports, so a component cannot be rendered via react-dom/server inside a
//      spec.
//
//   2. A REAL BROWSER pass over /chat. Unlike H10's components, H11's rendering
//      IS reachable from a page: ChatWindow already renders <MessageStream>,
//      and `selectSession` fetches GET /api/chat/sessions/{id}, which a
//      page.route() stub can answer with an assistant turn carrying the
//      contract. So the diff table, the evidence blocks and the suggested-action
//      links get genuine DOM assertions.
//
// WHAT THE BROWSER TESTS CANNOT COVER, stated rather than glossed:
//   The confirmation card and the clarification buttons are gated on handlers
//   that only task H12 supplies (H10's precedent — no visible control that does
//   nothing). Their logic is covered by the pure assertions below, and the
//   browser test asserts they stay dark, which is the H10 pattern exactly.
//
//   Separately: NOTHING on this contract reaches the browser from the real
//   backend yet, and that is a backend gap rather than an H11/H12 one.
//   `routers/chat.py::MessageResponse` declares no attachment field and the
//   persisted assistant `ChatMessage` row stores only content / generated_sql /
//   citations / result_invoice_ids, so FastAPI drops the agent's extra keys
//   before the response is serialised. These stubs are what the agent produces,
//   asserted cross-language below so they cannot drift silently.
// =============================================================================

import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
  ATTACHMENT_INTENT_PHRASE,
  DEFAULT_CLARIFICATION_OPTIONS,
  MAX_SUGGESTED_ACTIONS,
  buildComparisonRows,
  capSuggestedActions,
  clarificationOptions,
  comparisonStatusLabel,
  composeClarificationReply,
  evidencePageLabel,
  evidencePreview,
  formatComparisonAmount,
  formatComparisonDelta,
  type AttachmentComparisonEntry,
} from "@/lib/chatAttachments";

const QUERY_AGENT = path.resolve(
  __dirname,
  "../../invoice-be/agents/query_agent.py"
);

// -----------------------------------------------------------------------------
// Fixtures — shaped exactly like `compare_reference_to_invoices()` output
// (services/document_comparison.py L309/L338), including the string-typed money.
// -----------------------------------------------------------------------------
const varianceEntry: AttachmentComparisonEntry = {
  invoice_id: "11111111-1111-1111-1111-111111111111",
  invoice_number: "INV-2026-004",
  invoice_status: "AUDIT_REQUIRED",
  flow_direction: "INBOUND",
  outcome: "variance",
  reference_currency: "INR",
  invoice_currency: "INR",
  fields: [
    { field: "subtotal", reference_value: "1000.00", invoice_value: "1200.00", delta: "200.00", status: "invoice_higher" },
    { field: "tax_amount", reference_value: "180.00", invoice_value: "180.00", delta: "0.00", status: "match" },
    { field: "grand_total", reference_value: "1180.00", invoice_value: null, delta: null, status: "missing" },
  ],
  reference_line_count: 5,
  invoice_line_count: 7,
  line_count_delta: 2,
  blocked_reason: null,
};

const currencyMismatchEntry: AttachmentComparisonEntry = {
  invoice_id: "22222222-2222-2222-2222-222222222222",
  invoice_number: "INV-2026-009",
  invoice_status: "PAID",
  flow_direction: "INBOUND",
  outcome: "currency_mismatch",
  reference_currency: "EUR",
  invoice_currency: "INR",
  fields: [],
  blocked_reason:
    "The attached document is in EUR and this invoice is in INR. No amounts were compared: converting between currencies is not something this comparison does.",
};

// =============================================================================
test.describe("Feature 26 H11 — the diff table (§P2.6.4)", () => {
  test("a currency mismatch is a refusal row, never a zero delta", () => {
    const rows = buildComparisonRows(currencyMismatchEntry);

    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("refusal");
    // THE defect this test exists for: `_compare_one()` returns `fields: []`
    // for a currency mismatch, so any renderer that defaults a missing delta to
    // 0 reports that a EUR document and an INR invoice agree.
    expect(rows.some((r) => r.kind === "field")).toBe(false);
    if (rows[0].kind === "refusal") {
      expect(rows[0].reason).toContain("EUR");
      expect(rows[0].reason).toContain("INR");
      expect(rows[0].reason.toLowerCase()).toContain("no amounts were compared");
    }
  });

  test("a variance renders signed deltas and never turns 'missing' into zero", () => {
    const rows = buildComparisonRows(varianceEntry);
    const fields = rows.filter((r) => r.kind === "field");
    // 3 money fields + the line-count row.
    expect(fields).toHaveLength(4);

    const [subtotal, tax, grandTotal, lines] = fields as Extract<
      ReturnType<typeof buildComparisonRows>[number],
      { kind: "field" }
    >[];

    expect(subtotal.label).toBe("Subtotal");
    expect(subtotal.referenceValue).toBe("INR 1000.00");
    expect(subtotal.invoiceValue).toBe("INR 1200.00");
    expect(subtotal.delta).toBe("+200.00");
    expect(subtotal.outcome).toBe("Invoice higher");

    // A within-tolerance delta stays "0.00" — it is not signed, because it is
    // not a direction.
    expect(tax.delta).toBe("0.00");

    // `missing` means the side did not STATE the figure. The narration prompt
    // is explicitly told not to treat that as zero, and neither does the table.
    expect(grandTotal.invoiceValue).toBe("—");
    expect(grandTotal.delta).toBe("—");
    expect(grandTotal.outcome).toBe("Not stated");
    expect(comparisonStatusLabel("missing")).not.toContain("0");

    // The line-count difference is already computed by `_compare_one()`;
    // dropping it would hide a 5-line PO billed as 7 lines.
    expect(lines.label).toBe("Line items");
    expect(lines.delta).toBe("+2");
  });

  test("money is never parsed into a float on its way to the screen", () => {
    // 0.1 + 0.2 territory. The backend hands over Decimal-as-string precisely so
    // the exact figure survives; Number()-ing it to format would undo that.
    expect(formatComparisonAmount("1250.10", "INR")).toBe("INR 1250.10");
    expect(formatComparisonAmount("0.30", null)).toBe("0.30");
    expect(formatComparisonAmount(null, "INR")).toBe("—");
    expect(formatComparisonDelta("-45.55")).toBe("-45.55");
    expect(formatComparisonDelta("45.55")).toBe("+45.55");
    expect(formatComparisonDelta(null)).toBe("—");
  });
});

// =============================================================================
test.describe("Feature 26 H11 — suggested actions are links, capped at 3 (D6)", () => {
  test("the cap is 3 and holds regardless of what the payload sends", () => {
    expect(MAX_SUGGESTED_ACTIONS).toBe(3);
    const many = Array.from({ length: 6 }, (_, i) => ({
      label: `Action ${i}`,
      href: `/auditor/${i}`,
      precondition: "none",
      endpoint: `/api/v1/audit/resolve/${i}`,
      method: "PUT",
    }));
    expect(capSuggestedActions(many)).toHaveLength(3);
    expect(capSuggestedActions(undefined)).toHaveLength(0);
  });

  test("an action with no href is dropped rather than rendered as a dead link", () => {
    const actions = capSuggestedActions([
      { label: "Real one", href: "/trainer/abc" },
      { label: "No href", href: "" },
      { label: "", href: "/somewhere" },
    ] as any);
    expect(actions).toHaveLength(1);
    expect(actions[0].label).toBe("Real one");
  });

  test("the backend still emits href, and still does NOT emit §P2.8's `reason`", () => {
    // Cross-language drift check, in H10's style. §P2.8's sketch says
    // `{label, href, reason}`; `build_suggested_actions()` emits
    // `{label, endpoint, method, href, precondition}`. If the backend ever
    // changes that, this fails instead of the UI quietly rendering blanks.
    const source = fs.readFileSync(
      path.resolve(__dirname, "../../invoice-be/services/document_comparison.py"),
      "utf8"
    );
    expect(source).toContain('"precondition"');
    expect(source).toContain('"href"');
    expect(source).not.toContain('"reason":');
  });
});

// =============================================================================
test.describe("Feature 26 H11 — the clarifying turn's two choices (B2)", () => {
  test("both options render, in the order the question asks them", () => {
    const options = clarificationOptions({
      message: "Would you like me to read the document, or compare it to your invoices?",
      options: [
        { intent: "read", label: "Read the document" },
        { intent: "compare", label: "Compare to my invoices" },
      ],
    });
    expect(options.map((o) => o.intent)).toEqual(["read", "compare"]);
    // A turn that somehow arrives with no options still offers both rather than
    // stranding the user on a question with no answers.
    expect(clarificationOptions({ message: "x" })).toEqual(DEFAULT_CLARIFICATION_OPTIONS);
    // An intent this build cannot compose a re-send for is dropped, not shown.
    expect(
      clarificationOptions({ message: "x", options: [{ intent: "teleport", label: "?" }] })
    ).toHaveLength(0);
  });

  test("the choice re-sends the ORIGINAL question plus an explicit intent phrase", () => {
    const question = "What about this document?";
    expect(composeClarificationReply(question, "read")).toBe(
      `${question} — ${ATTACHMENT_INTENT_PHRASE.read}`
    );
    expect(composeClarificationReply(question, "compare")).toBe(
      `${question} — ${ATTACHMENT_INTENT_PHRASE.compare}`
    );
    // No preceding question (a reload that dropped it) still sends something
    // the classifier can resolve, rather than an empty message.
    expect(composeClarificationReply("", "compare")).toBe(ATTACHMENT_INTENT_PHRASE.compare);
    expect(composeClarificationReply(null, "read")).toBe(ATTACHMENT_INTENT_PHRASE.read);
  });

  test("each phrase resolves to exactly ONE branch of the real Python classifier", () => {
    // This is what "explicit intent" MEANS on this feature, verified rather than
    // assumed: there is no intent field on `MessageCreate`, so the phrase has to
    // win `_classify_attachment_intent()`'s keyword match on its own. The lists
    // are read out of query_agent.py so a keyword edit there fails here.
    const source = fs.readFileSync(QUERY_AGENT, "utf8");
    const comparison = extractKeywordTuple(source, "_COMPARISON_INTENT_KEYWORDS");
    const content = extractKeywordTuple(source, "_CONTENT_INTENT_KEYWORDS");

    expect(comparison.length).toBeGreaterThan(10);
    expect(content.length).toBeGreaterThan(10);

    const readPhrase = ATTACHMENT_INTENT_PHRASE.read;
    expect(matchesAny(readPhrase, content)).toBe(true);
    expect(matchesAny(readPhrase, comparison)).toBe(false);

    const comparePhrase = ATTACHMENT_INTENT_PHRASE.compare;
    expect(matchesAny(comparePhrase, comparison)).toBe(true);
    expect(matchesAny(comparePhrase, content)).toBe(false);
  });

  test("the clarification payload the FE renders is the one the agent emits", () => {
    // `_run_attached_document_turn()` L3199: message + options, read then compare.
    const source = fs.readFileSync(QUERY_AGENT, "utf8");
    expect(source).toContain('"attachment_clarification"');
    expect(source).toContain('{"intent": "read", "label": "Read the document"}');
    expect(source).toContain('{"intent": "compare", "label": "Compare to my invoices"}');
  });
});

/** Pulls a `_NAME = ( "a", "b", ... )` tuple of string literals out of Python source. */
function extractKeywordTuple(source: string, name: string): string[] {
  const start = source.indexOf(`${name} = (`);
  if (start === -1) throw new Error(`${name} not found in query_agent.py`);
  const end = source.indexOf("\n)", start);
  const body = source.slice(start, end);
  return Array.from(body.matchAll(/"([^"]+)"/g)).map((m) => m[1]);
}

/** The JS twin of `_compile_keyword_pattern()` — boundary-anchored, case-insensitive. */
function matchesAny(text: string, keywords: string[]): boolean {
  return keywords.some((k) =>
    new RegExp(`(?<!\\w)${k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!\\w)`, "i").test(text)
  );
}

// =============================================================================
test.describe("Feature 26 H11 — DocumentEvidence helpers", () => {
  test("a span with no page number still renders a label", () => {
    expect(evidencePageLabel({ page: 3 })).toBe("p.3");
    // Never "p.0": a null page is unknown, not page zero.
    expect(evidencePageLabel({ page: null })).toBe("Page ?");
    expect(evidencePageLabel({})).toBe("Page ?");
  });

  test("the collapsed preview truncates and collapses whitespace", () => {
    const long = "Payment terms: ".concat("net thirty days ".repeat(30));
    const preview = evidencePreview(long);
    expect(preview.length).toBeLessThanOrEqual(140);
    expect(preview.endsWith("…")).toBe(true);
    expect(evidencePreview("  net   30  ")).toBe("net 30");
    expect(evidencePreview("")).toBe("(no text)");
  });
});

// =============================================================================
// Browser pass — the contract rendered by a real MessageBubble on /chat
// =============================================================================

const SESSION_ID = "33333333-3333-3333-3333-333333333333";

const message = (over: Record<string, unknown>) => ({
  session_id: SESSION_ID,
  role: "assistant",
  content: "",
  generated_sql: null,
  citations: [],
  created_at: "2026-09-02T10:00:00Z",
  status: "completed",
  ...over,
});

const MESSAGES = [
  message({ id: "m1", role: "user", content: "Does this PO match what they billed?" }),
  message({
    id: "m2",
    content: "The invoice is higher than the purchase order on subtotal.",
    attachment_comparison: {
      reference: { doc_type: "PURCHASE_ORDER", doc_number: "PO-77", currency: "INR" },
      comparisons: [varianceEntry, currencyMismatchEntry],
      compared_count: 2,
      blocked_count: 1,
    },
    suggested_actions: [
      { label: "Review the flagged figures on this invoice", href: "/auditor/11111111-1111-1111-1111-111111111111", precondition: "status is AUDIT_REQUIRED", endpoint: "/api/v1/audit/resolve/x", method: "PUT" },
      { label: "Open this invoice in the Trainer to correct extraction", href: "/trainer/11111111-1111-1111-1111-111111111111", precondition: "none (read-only destination)", endpoint: "/api/v1/trainer/invoice/x", method: "GET" },
      { label: "Third action", href: "/outbound/1" },
      { label: "Fourth action the cap must drop", href: "/outbound/2" },
    ],
  }),
  message({ id: "m3", role: "user", content: "What are the payment terms?" }),
  message({
    id: "m4",
    content: "The document states net 30 days from the invoice date (p.2).",
    evidence: [
      { page: 2, text: "Payment terms: net thirty (30) days from the date of invoice. Late payment attracts interest at 1.5% per month, compounded monthly, until the outstanding balance is settled in full.", distance: 0.21 },
      { page: 4, text: "Delivery shall be completed within 14 days of the order date.", distance: 0.38 },
    ],
    needs_confirmation: false,
  }),
  message({ id: "m5", role: "user", content: "And this one?" }),
  message({
    id: "m6",
    content: "Would you like me to read the document, or compare it to your invoices?",
    attachment_clarification: {
      message: "Would you like me to read the document, or compare it to your invoices?",
      options: [
        { intent: "read", label: "Read the document" },
        { intent: "compare", label: "Compare to my invoices" },
      ],
    },
  }),
  message({ id: "m7", role: "user", content: "How many invoices are overdue?" }),
  // The regression case: an ordinary turn carrying none of the new fields.
  message({ id: "m8", content: "You have **3** overdue invoices." }),
];

async function openStubbedChat(page: import("@playwright/test").Page) {
  // The webServer is `next dev`, which compiles /chat on first request. With
  // four workers arriving at once that first compile alone can exceed the
  // default 30s test timeout — which is a build cost, not a product defect, so
  // it gets more time rather than a retry.
  test.setTimeout(150_000);

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
          title: "Attached PO thread",
          message_count: MESSAGES.length,
          created_at: "2026-09-02T09:00:00Z",
          updated_at: "2026-09-02T10:00:00Z",
        },
      ]),
    })
  );
  await page.route(`**/api/chat/sessions/${SESSION_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MESSAGES),
    })
  );

  await page.goto("/chat");
  await page.locator(`#chat-session-${SESSION_ID}`).click();
  await expect(page.locator("#chat-attachment-comparison")).toBeVisible();
}

test.describe("Feature 26 H11 — rendered on /chat", () => {
  test("the diff table renders both outcomes, and the mismatch is a refusal not a zero", async ({
    page,
  }) => {
    await openStubbedChat(page);

    const entries = page.locator('[data-testid="attachment-comparison-entry"]');
    await expect(entries).toHaveCount(2);

    // Entry 1 — a real variance, rendered as a table with a signed delta.
    const variance = entries.nth(0);
    await expect(variance).toHaveAttribute("data-outcome", "variance");
    await expect(variance.locator('[data-testid="attachment-comparison-field-row"]')).toHaveCount(4);
    await expect(variance.getByText("+200.00")).toBeVisible();
    await expect(variance.getByText("Not stated")).toBeVisible();

    // Entry 2 — the refusal. One row, no value columns, and no delta anywhere.
    const blocked = entries.nth(1);
    await expect(blocked).toHaveAttribute("data-outcome", "currency_mismatch");
    await expect(blocked.locator('[data-testid="attachment-comparison-refusal-row"]')).toHaveCount(1);
    await expect(blocked.locator('[data-testid="attachment-comparison-field-row"]')).toHaveCount(0);
    await expect(blocked.locator('[data-testid="attachment-comparison-delta"]')).toHaveCount(0);
    await expect(blocked).toContainText("No amounts were compared");
    await expect(blocked).toContainText("Not compared");
  });

  test("evidence blocks render collapsed and expand to the full quote", async ({ page }) => {
    await openStubbedChat(page);

    const evidence = page.locator("#chat-document-evidence");
    await expect(evidence).toBeVisible();
    await expect(evidence.locator('[data-testid="document-evidence-span"]')).toHaveCount(2);
    await expect(evidence.locator('[data-testid="document-evidence-header"]')).toContainText(
      "2 passages"
    );
    await expect(evidence.locator('[data-testid="document-evidence-span"]').first()).toContainText(
      "p.2"
    );

    // Collapsed: the full quote is not in the DOM yet.
    await expect(evidence.locator('[data-testid="document-evidence-text"]')).toHaveCount(0);
    await evidence.locator('[data-testid="document-evidence-toggle-0"]').click();
    const quote = evidence.locator('[data-testid="document-evidence-text"]');
    await expect(quote).toHaveCount(1);
    await expect(quote).toContainText("compounded monthly");

    // It cites the attached document — so, unlike CitationPill, it navigates
    // nowhere. There is no audit record behind an attachment span (D2).
    await expect(evidence.locator("a")).toHaveCount(0);
    await expect(page).toHaveURL(/\/chat$/);
  });

  test("suggested actions render as links, not buttons, and stop at 3", async ({ page }) => {
    await openStubbedChat(page);

    const actions = page.locator('[data-testid="chat-suggested-action"]');
    // The payload deliberately carries 4; D6's cap drops the last.
    await expect(actions).toHaveCount(3);
    await expect(page.getByText("Fourth action the cap must drop")).toHaveCount(0);

    for (let i = 0; i < 3; i += 1) {
      // A link, not a <button> — chat never invokes a mutating endpoint (D6),
      // and an <a href> cannot be mistaken for one.
      expect(await actions.nth(i).evaluate((el) => el.tagName)).toBe("A");
      expect(await actions.nth(i).getAttribute("href")).toBeTruthy();
    }
    await expect(page.locator("#chat-suggested-actions").locator("button")).toHaveCount(0);
  });

  test("a message with none of these fields renders exactly as it does today", async ({ page }) => {
    await openStubbedChat(page);

    // The plain SQL-route-shaped answer still renders its markdown bubble, and
    // adds no contract chrome of its own.
    const plain = page.getByText("You have 3 overdue invoices.");
    await expect(plain).toBeVisible();
    // Bold survived react-markdown, i.e. the existing renderer is untouched.
    await expect(plain.locator("strong")).toHaveText("3");

    // Exactly one of each container across the whole thread — the plain message
    // contributed none.
    await expect(page.locator("#chat-attachment-comparison")).toHaveCount(1);
    await expect(page.locator("#chat-document-evidence")).toHaveCount(1);
    await expect(page.locator("#chat-suggested-actions")).toHaveCount(1);
    await expect(page.locator('[data-testid="attachment-needs-confirmation"]')).toHaveCount(0);
  });

  test("the clarifying turn shows its question; the choices stay dark until the handlers are threaded", async ({
    page,
  }) => {
    await openStubbedChat(page);

    // The prose renders — nothing the backend said is hidden.
    await expect(
      page.getByText("Would you like me to read the document, or compare it to your invoices?")
    ).toBeVisible();

    // ChatWindow renders `<MessageStream messages isSending />` and passes no
    // `attachmentHandlers` (L722 as of this commit — H12 landed the composer,
    // the hook and the proxy routes in parallel with H11 and could not thread a
    // prop that did not exist yet). So the two choice buttons and the
    // confirmation card are not rendered at all rather than rendered dead,
    // which is H10's precedent and the same reasoning.
    //
    // THIS ASSERTION IS MEANT TO FLIP. Whoever threads
    // `attachmentHandlers={...}` from `useChatSession` into `<MessageStream>`
    // should invert these two counts and drive the buttons for real — exactly
    // as H12 inverted H10's `#chat-attach-btn` count when it lit the paperclip.
    await expect(page.locator("#chat-attachment-clarification")).toHaveCount(0);
    await expect(page.locator("#chat-attachment-match-confirm")).toHaveCount(0);
  });
});
