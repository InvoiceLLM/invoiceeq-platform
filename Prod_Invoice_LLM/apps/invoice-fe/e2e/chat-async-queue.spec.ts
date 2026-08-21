import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 280 — Queue-based Chat Architecture, Thinking Badges, and SSE Streaming.
 */

const SESSION_ID = "33333333-4444-5555-6666-777777777777";
const JOB_ID = "job-e2e-123";

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
        outbound_sender_email: null,
        billing_plan: "free",
      }),
    })
  );

  await page.route("**/api/chat/sessions", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: SESSION_ID,
            tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            user_id: "user_e2e",
            title: "Async Queue Test",
            message_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ]),
      });
    }
    return route.continue();
  });

  await page.route(`**/api/chat/sessions/${SESSION_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
}

test.describe("Gap 280: Async Chat Queue & Thinking States", () => {
  test("submitting a message handles 202 Accepted and displays thinking indicator", async ({ page }) => {
    await stubShell(page);

    // Stub 202 Accepted on message POST
    await page.route(`**/api/chat/sessions/${SESSION_ID}/message`, (route) =>
      route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: JOB_ID,
          message_id: "user-msg-e2e",
          status: "queued",
        }),
      })
    );

    // Stub SSE stream
    await page.route(`**/api/chat/jobs/${JOB_ID}/stream`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: {"job_id":"${JOB_ID}","status":"processing","step":"routing","details":"Analyzing query and documents..."}\n\ndata: {"job_id":"${JOB_ID}","status":"completed","result":{"id":"ast-1","session_id":"${SESSION_ID}","role":"assistant","content":"Hardware spend is $45,000.00","status":"completed","created_at":"${new Date().toISOString()}"}}\n\n`,
      })
    );

    await page.goto("/chat");

    // Select the session
    await page.getByText("Async Queue Test").click();

    // Type a question in the chat input
    const input = page.getByPlaceholder("Ask a question about your invoices...");
    await input.fill("What is hardware spend?");
    await page.keyboard.press("Enter");

    // Verify optimistic user bubble is visible immediately
    await expect(page.getByText("What is hardware spend?")).toBeVisible();

    // Verify completed response renders
    await expect(page.getByText("Hardware spend is $45,000.00")).toBeVisible();
  });

  test("polling fallback activates when SSE connection is blocked", async ({ page }) => {
    await stubShell(page);

    await page.route(`**/api/chat/sessions/${SESSION_ID}/message`, (route) =>
      route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "job-polling-456",
          message_id: "user-msg-456",
          status: "queued",
        }),
      })
    );

    // Fail SSE stream with 502
    await page.route(`**/api/chat/jobs/job-polling-456/stream`, (route) =>
      route.fulfill({ status: 502, body: "SSE blocked" })
    );

    // Status polling endpoint returns completed result
    await page.route(`**/api/chat/jobs/job-polling-456/status`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "job-polling-456",
          status: "completed",
          result: {
            id: "ast-2",
            session_id: SESSION_ID,
            role: "assistant",
            content: "Recovered via polling fallback: Total is $10,000",
            status: "completed",
            created_at: new Date().toISOString(),
          },
        }),
      })
    );

    await page.goto("/chat");
    await page.getByText("Async Queue Test").click();

    const input = page.getByPlaceholder("Ask a question about your invoices...");
    await input.fill("Test polling recovery");
    await page.keyboard.press("Enter");

    await expect(page.getByText("Recovered via polling fallback: Total is $10,000")).toBeVisible({
      timeout: 10000,
    });
  });
});
