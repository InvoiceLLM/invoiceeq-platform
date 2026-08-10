import { test, expect } from "@playwright/test";

/**
 * Public SendGrid Inbound Parse pass-through
 * (`app/api/v1/email/mailintegration/route.ts`).
 *
 * Same constraints as billing-payu-relay.spec.ts: with BACKEND_API_URL pinned
 * to a dead port in playwright.config.ts, we assert the relay's own
 * unreachable-backend branch (502 JSON), not a live forward to invoice-be.
 */

test.describe("POST /api/v1/email/mailintegration — backend unreachable", () => {
  test("returns 502 JSON relay_error when BACKEND_API_URL is unreachable", async ({
    request,
  }) => {
    const response = await request.post("/api/v1/email/mailintegration", {
      multipart: {
        to: "invoices@invoiceeq.app",
        from: "ap@example.com",
      },
    });

    expect(response.status()).toBe(502);
    const body = await response.json();
    expect(body.success).toBe(false);
    expect(body.status).toBe("relay_error");
  });
});
