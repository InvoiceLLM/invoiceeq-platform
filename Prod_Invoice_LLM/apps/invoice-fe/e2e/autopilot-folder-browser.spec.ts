import { test, expect } from "@playwright/test";

test.describe("Autopilot folder browser (FE Gap 219)", () => {
  test("browse selects folder into autopilot source_ref", async ({ page }) => {
    await page.route("**/api/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          role: "Admin",
          billing_plan: "pro",
          email: "admin@test.com",
        }),
      });
    });

    await page.route("**/api/autopilot/config", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            source_type: "gdrive",
            source_ref: "",
            flow_direction: "INBOUND",
            trigger_mode: "interval",
            trigger_value: "60",
            notify_emails: [],
            send_approval_links: false,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route("**/api/connectors/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ google_drive: "Active", salesforce: "Inactive" }),
      });
    });

    await page.route("**/api/connectors/files/google_drive**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          files: [
            { id: "folder-abc", name: "Invoices Inbox", type: "folder", size_bytes: 0 },
          ],
        }),
      });
    });

    await page.goto("/ingestion");
    await page.getByRole("button", { name: "Autopilot" }).click();
    const browseBtn = page.getByRole("button", { name: /Browse/i });
    await expect(browseBtn).toBeVisible({ timeout: 15_000 });
    await browseBtn.click();
    await expect(page.getByRole("button", { name: "Select This Folder" })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByText("Invoices Inbox").click();
    await page.getByRole("button", { name: "Select This Folder" }).click();

    await expect(page.getByText("Invoices Inbox")).toBeVisible();
  });
});
