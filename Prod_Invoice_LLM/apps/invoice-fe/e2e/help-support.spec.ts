import { test, expect, Page } from "@playwright/test";

/**
 * Feature 15 / Gaps 240-242: Help Center Knowledge Base & AI Support Assistant with Direct Ticket Escalation.
 *
 * Tests:
 * 1. Default View: /help opens Knowledge Base Guides tab by default on initial load.
 * 2. Search Filter: Filtering guides updates visible topics.
 * 3. Tab Switcher: Switching to "AI Support Assistant" loads SAGE bot chat interface.
 * 4. Chat Guidance: Sending a query returns assistant response.
 * 5. Smart Escalation: Error keyword triggers inline [Raise Support Ticket from this Issue] card.
 * 6. Modal Pre-fill: Escalation trigger pre-populates subject, category, and priority in modal.
 * 7. Direct Ticket Trigger: Single direct ticket button in chat header opens clean modal and submits successfully.
 *
 * FE Gap 404 (Ticket History & Status portal):
 * 8. My Tickets tab lists the tenant's own tickets from GET /api/support/ticket.
 * 9. My Tickets tab shows the empty state when the tenant has no tickets.
 */

async function stubShell(page: Page) {
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
      }),
    })
  );
}

async function gotoHelp(page: Page) {
  for (let attempt = 0; ; attempt++) {
    try {
      await page.goto("/help", { waitUntil: "domcontentloaded", timeout: 60_000 });
      break;
    } catch (err) {
      if (attempt >= 2) throw err;
    }
  }
  await expect(page.locator("#tab-btn-guides")).toBeVisible({ timeout: 15_000 });
}

test.describe("Feature 15: Help Center & AI Support Assistant", () => {
  test.beforeEach(async ({ page }) => {
    test.slow();
    await stubShell(page);
  });

  test("1. opens Knowledge Base Guides by default on initial load", async ({ page }) => {
    await gotoHelp(page);

    // Guides tab is active by default
    const guidesTab = page.locator("#tab-btn-guides");
    await expect(guidesTab).toHaveAttribute("aria-selected", "true");

    // Guide container is visible with topic sidebar
    await expect(page.locator("#help-guides-container")).toBeVisible();
    await expect(page.locator("#help-guide-search")).toBeVisible();
  });

  test("2. search filters knowledge base guide topics", async ({ page }) => {
    await gotoHelp(page);

    const searchInput = page.locator("#help-guide-search");
    await searchInput.fill("trainer");

    // Topics matching trainer are rendered
    await expect(page.locator("#guide-item-overview")).toBeVisible();
  });

  test("3. switches to AI Support Assistant tab and displays SAGE interface", async ({ page }) => {
    await gotoHelp(page);

    const assistantTab = page.locator("#tab-btn-assistant");
    await assistantTab.click();

    await expect(assistantTab).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#support-chat-window")).toBeVisible();
    await expect(page.locator("#direct-raise-ticket-btn")).toBeVisible();
    await expect(page.locator("#prompt-chip-0")).toBeVisible();
  });

  test("4. sends message and receives troubleshooting response", async ({ page }) => {
    await page.route("**/api/support/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "To train a vendor format, navigate to `/trainer` and upload a sample invoice.",
          suggest_escalation: false,
          escalation_context: null,
        }),
      })
    );

    await gotoHelp(page);
    await page.locator("#tab-btn-assistant").click();

    const input = page.locator("#support-chat-input");
    await input.fill("How do I train a new vendor format?");
    await page.locator("#send-support-chat-btn").click();

    await expect(page.locator("#support-chat-messages")).toContainText("To train a vendor format");
  });

  test("5. smart escalation card appears on system error and pre-fills ticket modal", async ({ page }) => {
    await page.route("**/api/support/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "Gateway timeout detected during batch sync.",
          suggest_escalation: true,
          escalation_context: {
            category: "TECHNICAL_SUPPORT",
            priority: "URGENT",
            subject: "System Timeout / Batch Sync Failure",
            errorCode: "ERR_GATEWAY_TIMEOUT_504",
          },
        }),
      })
    );

    await page.route("**/api/support/ticket", (route) =>
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          ticket_number: "TICK-2026-9812",
          message: "Your support ticket has been raised. Reference: TICK-2026-9812.",
          email_dispatched: true,
        }),
      })
    );

    await gotoHelp(page);
    await page.locator("#tab-btn-assistant").click();

    const promptChip = page.locator("#prompt-chip-3"); // 504 error chip
    await promptChip.click();

    // Escalation card renders
    const escalationCard = page.locator("#smart-escalation-card");
    await expect(escalationCard).toBeVisible();

    // Click escalate
    await page.locator("#escalate-ticket-btn").click();

    // Modal opens with pre-filled subject
    const modalOverlay = page.locator("#support-ticket-modal-overlay");
    await expect(modalOverlay).toBeVisible();
    await expect(page.locator("#ticket-subject")).toHaveValue("System Timeout / Batch Sync Failure");

    // Submit ticket
    await page.locator("#submit-ticket-btn").click();

    // Success card renders with generated ticket number
    await expect(page.locator("#ticket-success-card")).toBeVisible();
    await expect(page.locator("#ticket-success-card")).toContainText("TICK-2026-9812");
  });

  test("6. direct raise ticket button in chat header opens clean modal and submits", async ({ page }) => {
    await page.route("**/api/support/ticket", (route) =>
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          ticket_number: "TICK-2026-1122",
          message: "Your support ticket has been raised. Reference: TICK-2026-1122.",
          email_dispatched: true,
        }),
      })
    );

    await gotoHelp(page);
    await page.locator("#tab-btn-assistant").click();

    // Click direct ticket button in header
    await page.locator("#direct-raise-ticket-btn").click();

    const modalOverlay = page.locator("#support-ticket-modal-overlay");
    await expect(modalOverlay).toBeVisible();

    // Fill form
    await page.locator("#ticket-subject").fill("Need custom webhook endpoint help");
    await page.locator("#ticket-description").fill("We need assistance verifying HMAC signatures in Python.");

    // Submit
    await page.locator("#submit-ticket-btn").click();

    await expect(page.locator("#ticket-success-card")).toBeVisible();
    await expect(page.locator("#ticket-success-card")).toContainText("TICK-2026-1122");
  });

  test("8. My Tickets tab lists the tenant's own tickets", async ({ page }) => {
    await page.route("**/api/support/ticket", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tickets: [
            {
              ticket_number: "TICK-2026-4471",
              subject: "Webhook signature verification failing",
              category: "TECHNICAL_SUPPORT",
              priority: "URGENT",
              status: "OPEN",
              source: "HELP_CHATBOT",
              created_at: "2026-09-01T10:15:00Z",
            },
            {
              ticket_number: "TICK-2026-3390",
              subject: "Question about Pro Combined plan limits",
              category: "BILLING",
              priority: "NORMAL",
              status: "RESOLVED",
              source: "DIRECT_TICKET",
              created_at: "2026-08-28T14:02:00Z",
            },
          ],
        }),
      });
    });

    await gotoHelp(page);
    await page.locator("#tab-btn-tickets").click();

    await expect(page.locator("#tab-btn-tickets")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#ticket-history-panel")).toBeVisible();
    await expect(page.locator("#ticket-history-panel")).toContainText("TICK-2026-4471");
    await expect(page.locator("#ticket-history-panel")).toContainText("Webhook signature verification failing");
    await expect(page.locator("#ticket-history-panel")).toContainText("TICK-2026-3390");
  });

  test("9. My Tickets tab shows the empty state with no tickets", async ({ page }) => {
    await page.route("**/api/support/ticket", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tickets: [] }),
      });
    });

    await gotoHelp(page);
    await page.locator("#tab-btn-tickets").click();

    await expect(page.locator("#ticket-history-empty-state")).toBeVisible();
    await expect(page.locator("#ticket-history-empty-state")).toContainText("No tickets yet");
  });
});
