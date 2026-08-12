import { test, expect, Page } from "@playwright/test";

/**
 * FE Gap 216 — chat thread rename must persist server-side.
 *
 * The defect these specs guard: `app/api/chat/sessions/[sessionId]/route.ts`
 * exported only GET and DELETE, so `useChatSession.renameSession()`'s PUT got a
 * 405 from Next.js — and its catch branch applied the new title to local React
 * state anyway. The rename therefore looked applied, raised no error, and
 * reverted on the next load because nothing had been written.
 *
 * That is why the persistence test below reloads the page and re-reads the list
 * from the (stubbed) backend rather than asserting on the sidebar right after
 * the edit: the broken build passes the immediate assertion. The stub keeps a
 * mutable store so only a real PUT reaching it can change what a later GET
 * returns — a client-state-only rename leaves the store untouched.
 *
 * Scope limit, verified rather than assumed: `page.route()` intercepts in the
 * browser, *before* Next.js is reached, so the two page-driven tests cover the
 * hook half of the fix but cannot see whether the proxy route exists at all —
 * confirmed by deleting the PUT export and watching them still pass. The third
 * test drives the dev server directly through the `request` fixture, which no
 * page route can shadow, and is the one that fails when that export is missing.
 */

const SESSION_ID = "11111111-2222-3333-4444-555555555555";

interface StubbedSession {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors the four other specs' shell stub — identity plus the calls the app
 *  shell itself makes, so the chat page renders without unrelated failures. */
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

  await page.route("**/api/invoices**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "x-total-count": "0" },
      body: "[]",
    })
  );
}

/**
 * Stands in for the backend's session store. `renamePut` decides how
 * `PUT /chat/sessions/{id}` behaves, so the same fixture covers both the fixed
 * path and a rejected rename. Returns the store so a test can assert what the
 * "server" actually holds, independently of what the UI shows.
 */
async function stubChatSessions(
  page: Page,
  opts: { renamePut: "ok" | "405" } = { renamePut: "ok" }
) {
  const store: StubbedSession[] = [
    {
      id: SESSION_ID,
      tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      user_id: "user_e2e",
      title: "Original thread name",
      message_count: 0,
      created_at: "2026-08-01T10:00:00Z",
      updated_at: "2026-08-01T10:00:00Z",
    },
  ];

  // GET /api/chat/sessions -- the list the sidebar renders. Always served from
  // the mutable store, so a reload reflects writes and only writes.
  await page.route("**/api/chat/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(store),
    })
  );

  // `*` does not cross a `/`, so this matches /api/chat/sessions/{id} but not
  // /api/chat/sessions/{id}/message.
  await page.route("**/api/chat/sessions/*", async (route) => {
    const request = route.request();

    if (request.method() === "PUT") {
      if (opts.renamePut === "405") {
        // Exactly what Next.js returned before this gap was fixed: the route
        // file existed but exported no PUT handler.
        await route.fulfill({ status: 405, contentType: "application/json", body: "{}" });
        return;
      }
      const { title } = JSON.parse(request.postData() ?? "{}") as { title?: string };
      const saved = (title ?? "").trim();
      const row = store.find((s) => s.id === SESSION_ID);
      if (row) row.title = saved;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...row, title: saved }),
      });
      return;
    }

    // GET -- message history for the thread; empty is fine, no message assertions here.
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  return store;
}

const threadRow = (page: Page) => page.locator(`#chat-session-${SESSION_ID}`);

/** Opens the inline editor, types a new title, and submits the form. */
async function renameThread(page: Page, newTitle: string) {
  const row = threadRow(page);
  await expect(row).toBeVisible();
  await row.getByTitle("Rename thread").click();

  const input = row.locator('form input[type="text"]');
  await expect(input).toBeVisible();
  await input.fill(newTitle);
  await input.press("Enter");
}

test.describe("Chat thread rename (FE Gap 216)", () => {
  test("the new title survives a reload, because it was written server-side", async ({ page }) => {
    await stubShell(page);
    const store = await stubChatSessions(page);

    await page.goto("/chat");
    await expect(threadRow(page)).toContainText("Original thread name");

    const putRequest = page.waitForRequest(
      (r) => r.method() === "PUT" && r.url().includes(`/api/chat/sessions/${SESSION_ID}`)
    );
    await renameThread(page, "Q3 vendor disputes");
    await putRequest;

    await expect(threadRow(page)).toContainText("Q3 vendor disputes");
    // The assertion the broken build could not pass: the write reached the
    // backend, not just React state.
    expect(store[0].title).toBe("Q3 vendor disputes");

    await page.reload();
    await expect(threadRow(page)).toContainText("Q3 vendor disputes");
    await expect(threadRow(page)).not.toContainText("Original thread name");
  });

  test("a rejected rename surfaces an error and leaves the old title on screen", async ({ page }) => {
    await stubShell(page);
    const store = await stubChatSessions(page, { renamePut: "405" });

    await page.goto("/chat");
    await expect(threadRow(page)).toContainText("Original thread name");

    await renameThread(page, "Never saved");

    // Previously this was the silent-success path: the sidebar showed the new
    // name with no error, then reverted on reload.
    await expect(page.getByText("Failed to rename this chat session.")).toBeVisible();
    await expect(threadRow(page)).toContainText("Original thread name");
    await expect(threadRow(page)).not.toContainText("Never saved");
    expect(store[0].title).toBe("Original thread name");
  });

  test("the PUT proxy route itself exists — Next.js no longer answers 405", async ({ request }) => {
    // Goes to the dev server directly (no page, so no page.route() stub can
    // shadow it). 405 is exactly the defect: app/api/chat/sessions/[sessionId]/
    // route.ts exported only GET and DELETE, so Next.js rejected the method
    // before any handler ran. Any other status means the handler was invoked --
    // here it fails downstream because no FastAPI backend is running behind the
    // dev server, which is not what this test is about. Asserting "not 405"
    // rather than "200" keeps it honest about what it can prove without a
    // backend, while still failing the moment that export is removed.
    const res = await request.put(`/api/chat/sessions/${SESSION_ID}`, {
      data: { title: "Proxy route reachability check" },
    });
    expect(res.status()).not.toBe(405);
  });
});
