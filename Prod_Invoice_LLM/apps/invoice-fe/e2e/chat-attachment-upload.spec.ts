// =============================================================================
// FILE: e2e/chat-attachment-upload.spec.ts
// FEATURE: BE Feature 26 Part 2, task H12 (§P2.6.6–§P2.6.7) — useChatSession's
//          upload/confirm/reload plumbing, the three Next proxy routes, and the
//          page wiring that makes H10's composer control reachable at all.
//
// WHAT MAKES THESE DIFFERENT FROM H10's SPEC, which is the point of this file:
//   chat-attachment-guards.spec.ts asserts pure functions in
//   lib/chatAttachments.ts, because until today nothing rendered the components
//   that consume them. These tests drive the REAL UI: a real click on the real
//   paperclip, a real <input type="file">, the hook's real XMLHttpRequest, and
//   the real state machine — and they assert the CALL SHAPE (method, URL,
//   multipart body, and that `attachment_id` reaches the message request), not
//   only what the DOM ends up showing.
//
// WHAT IS STUBBED AND WHY — stated plainly rather than implied:
//   The backend responses are stubbed with page.route(), exactly as every other
//   spec in this directory does (playwright.config.ts starts `next dev` and
//   nothing else — no FastAPI, no Postgres, no Chroma, no Document
//   Intelligence). So this is NOT a claim that the backend behaves as stubbed;
//   the backend's own behaviour is covered by tests/test_chat_attachments.py.
//   What IS proven here is everything on this side of the HTTP boundary: that
//   the browser issues the right request to the right URL through the right
//   proxy, that the four-state chip advances on real XHR events, and that the
//   composer's send carries the attachment.
//
//   The two JSON proxy routes are additionally asserted to EXIST in Next's
//   router (they do not 404) by calling them directly — see the last describe
//   block, which states exactly what that does and does not prove.
// =============================================================================

import { test, expect, type Page, type Route } from "@playwright/test";

const SESSION_ID = "11111111-2222-3333-4444-555555555555";
const ATTACHMENT_ID = "99999999-8888-7777-6666-555555555555";

/** A byte payload big enough to be a real multipart body, small enough to be fast. */
const PDF_BYTES = Buffer.concat([
  Buffer.from("%PDF-1.7\n"),
  Buffer.alloc(400_000, 0x41),
  Buffer.from("\n%%EOF\n"),
]);

const PICKED_FILE = {
  name: "purchase-order-4471.pdf",
  mimeType: "application/pdf",
  buffer: PDF_BYTES,
};

/** `AttachmentOut` as `routers/chat_attachments.py::_to_out` actually emits it. */
function attachmentOut(overrides: Record<string, unknown> = {}) {
  return {
    id: ATTACHMENT_ID,
    session_id: SESSION_ID,
    filename: PICKED_FILE.name,
    doc_type: "PURCHASE_ORDER",
    extraction_status: "EXTRACTED",
    doc_number: "PO-4471",
    party_name: "Northwind Supplies Ltd",
    doc_date: "2026-08-14",
    currency: "INR",
    grand_total: 125000.0,
    file_size_bytes: PDF_BYTES.length,
    candidate_invoice_ids: [],
    confirmed_invoice_ids: [],
    ...overrides,
  };
}

interface Recorded {
  upload: { method: string; url: string; contentType: string; body: string }[];
  message: { url: string; body: unknown }[];
  attachmentGet: string[];
}

/**
 * Stubs everything /chat needs and records the two requests these tests are
 * actually about. `uploadResponse` is a function so a test can choose the
 * status/body per case (accepted, 413, EXTRACT_FAILED).
 */
async function setupChat(
  page: Page,
  opts: {
    uploadResponse?: (route: Route) => Promise<void>;
    messageResponse?: Record<string, unknown>;
    uploadDelayMs?: number;
  } = {}
): Promise<Recorded> {
  const recorded: Recorded = { upload: [], message: [], attachmentGet: [] };

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

  const session = {
    id: SESSION_ID,
    tenant_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    user_id: "user_e2e",
    title: "Attachment session",
    message_count: 0,
    created_at: "2026-09-02T10:00:00Z",
    updated_at: "2026-09-02T10:00:00Z",
  };

  // GET list / POST create
  await page.route("**/api/chat/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(route.request().method() === "POST" ? session : [session]),
    })
  );
  // GET one session's messages
  await page.route("**/api/chat/sessions/*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );

  // The upload under test.
  await page.route("**/api/chat/sessions/*/attachments", async (route) => {
    const request = route.request();
    recorded.upload.push({
      method: request.method(),
      url: request.url(),
      contentType: request.headers()["content-type"] ?? "",
      body: request.postData() ?? "",
    });
    // A real upload is not instantaneous, and the chip's "extracting" state is
    // a real server-side wait (Document Intelligence runs inside this request).
    // The delay makes that observable instead of a frame the test can never see.
    if (opts.uploadDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, opts.uploadDelayMs));
    }
    if (opts.uploadResponse) {
      await opts.uploadResponse(route);
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(attachmentOut()),
    });
  });

  // The message send — this is where `attachment_id` has to appear.
  await page.route("**/api/chat/sessions/*/message", async (route) => {
    const raw = route.request().postData() ?? "{}";
    recorded.message.push({ url: route.request().url(), body: JSON.parse(raw) });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        opts.messageResponse ?? {
          id: "msg-1",
          session_id: SESSION_ID,
          role: "assistant",
          content: "Here is what I found.",
          status: "completed",
          created_at: "2026-09-02T10:01:00Z",
        }
      ),
    });
  });

  // The reload/reattach read.
  await page.route("**/api/chat/attachments/*", async (route) => {
    recorded.attachmentGet.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(attachmentOut()),
    });
  });

  return recorded;
}

/** Opens /chat and starts a session, so the composer is enabled. */
async function openChatWithSession(page: Page) {
  await page.goto("/chat");
  await page.locator("#chat-new-session-btn").click();
  await expect(page.locator("#chat-input-textarea")).toBeEnabled();
}

test.describe("Feature 26 H12 — the paperclip is reachable from /chat", () => {
  // THE claim this task exists to make true. H10 shipped the control
  // deliberately dark (it renders only when `onAttach` is supplied, and nothing
  // supplied it); this asserts that app/chat/page.tsx now does.
  test("a real user on /chat sees an enabled attach control", async ({ page }) => {
    await setupChat(page);
    await openChatWithSession(page);

    const paperclip = page.locator("#chat-attach-btn");
    await expect(paperclip).toBeVisible();
    await expect(paperclip).toBeEnabled();
    // The hidden input is what a real click reaches, and it must still carry
    // H10's guards: PDF only, single file.
    const input = page.locator('[data-testid="chat-attach-input"]');
    await expect(input).toHaveAttribute("accept", ".pdf");
    expect(await input.getAttribute("multiple")).toBeNull();
  });

  test("with no session selected the composer is disabled, attach included", async ({
    page,
  }) => {
    await setupChat(page);
    await page.goto("/chat");
    // No session picked yet: the send button and the paperclip share the same
    // disabled condition, and attaching to nothing would have no URL to POST to.
    await expect(page.locator("#chat-attach-btn")).toBeDisabled();
  });
});

test.describe("Feature 26 H12 — a real upload through the real UI", () => {
  test("picking a PDF uploads it by XHR and the chip reaches ready", async ({ page }) => {
    const recorded = await setupChat(page, { uploadDelayMs: 1200 });
    await openChatWithSession(page);

    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);

    const chip = page.locator("#chat-attachment-chip");
    await expect(chip).toBeVisible();
    // The server-side wait is a real state, not a frame: the request is held
    // open for 1.2s above and the chip must say what is happening during it.
    await expect(chip).toHaveAttribute("data-attachment-status", "extracting");
    await expect(chip).toHaveAttribute("data-attachment-status", "ready");

    // The five fields AttachmentOut returns are what the ready chip renders.
    await expect(chip).toContainText("PURCHASE ORDER");
    await expect(chip).toContainText("PO-4471");
    await expect(chip).toContainText("Northwind Supplies Ltd");

    // --- the call shape, which is the half a DOM assertion cannot prove ------
    expect(recorded.upload).toHaveLength(1);
    const call = recorded.upload[0];
    expect(call.method).toBe("POST");
    expect(new URL(call.url).pathname).toBe(
      `/api/chat/sessions/${SESSION_ID}/attachments`
    );
    // Multipart, with the boundary the browser generated — proof this went out
    // as a real file upload and not a JSON body with a filename in it.
    expect(call.contentType).toContain("multipart/form-data");
    expect(call.contentType).toContain("boundary=");
    // Field name must be "file": FastAPI's `file: UploadFile = File(...)` 422s
    // on anything else, and that mismatch is invisible from the DOM.
    expect(call.body).toContain('name="file"');
    expect(call.body).toContain(PICKED_FILE.name);
  });

  test("the composer's send then carries attachment_id", async ({ page }) => {
    const recorded = await setupChat(page);
    await openChatWithSession(page);

    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);
    await expect(page.locator("#chat-attachment-chip")).toHaveAttribute(
      "data-attachment-status",
      "ready"
    );

    await page.locator("#chat-input-textarea").fill("Does this PO match what we were billed?");
    await page.locator("#chat-send-btn").click();

    await expect.poll(() => recorded.message.length).toBe(1);
    const body = recorded.message[0].body as Record<string, unknown>;
    expect(body.content).toBe("Does this PO match what we were billed?");
    // The whole point of H12: without this field the backend's deterministic
    // pre-route gate (D4) never fires and the question is answered as an
    // ordinary chat turn, silently ignoring the document.
    expect(body.attachment_id).toBe(ATTACHMENT_ID);

    // An answered turn releases the document, so the NEXT question is not
    // silently re-grounded in it (§P2.6.6).
    await expect(page.locator("#chat-attachment-chip")).toHaveCount(0);
  });

  test("a turn with no attachment sends no attachment_id at all", async ({ page }) => {
    const recorded = await setupChat(page);
    await openChatWithSession(page);

    await page.locator("#chat-input-textarea").fill("What did we spend last month?");
    await page.locator("#chat-send-btn").click();

    await expect.poll(() => recorded.message.length).toBe(1);
    const body = recorded.message[0].body as Record<string, unknown>;
    // Absent, not null: every ordinary turn's request stays byte-identical to
    // what this app sent before Feature 26 existed.
    expect("attachment_id" in body).toBe(false);
  });

  test("a confirmation turn KEEPS the document attached", async ({ page }) => {
    // The deliberate deviation from §P2.6.6's flat "clear on success": a
    // confirmation turn answers nothing and the follow-up must carry the same
    // attachment_id, or confirming a match set would be thrown away and the
    // user would have to re-upload the document to get their answer.
    const recorded = await setupChat(page, {
      messageResponse: {
        id: "msg-confirm",
        session_id: SESSION_ID,
        role: "assistant",
        content: "Which of these invoices should I compare it to?",
        status: "completed",
        created_at: "2026-09-02T10:01:00Z",
        attachment_confirmation: {
          kind: "attachment_match_confirmation",
          attachment_id: ATTACHMENT_ID,
          tier: 1,
          candidates: [],
          requires_manual_entry: false,
          message: "I found one invoice with this PO number.",
        },
      },
    });
    await openChatWithSession(page);

    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);
    await expect(page.locator("#chat-attachment-chip")).toHaveAttribute(
      "data-attachment-status",
      "ready"
    );

    await page.locator("#chat-input-textarea").fill("Compare this to my invoices");
    await page.locator("#chat-send-btn").click();
    await expect.poll(() => recorded.message.length).toBe(1);

    // Still attached, so the confirmed follow-up can reach the same document.
    await expect(page.locator("#chat-attachment-chip")).toHaveAttribute(
      "data-attachment-status",
      "ready"
    );
  });
});

test.describe("Feature 26 H12 — the two failures stay distinguishable", () => {
  test("a 413 shows the backend's own message and attaches nothing", async ({ page }) => {
    const recorded = await setupChat(page, {
      uploadResponse: (route) =>
        route.fulfill({
          status: 413,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Attachments are limited to 10 MB." }),
        }),
    });
    await openChatWithSession(page);

    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);

    const chip = page.locator("#chat-attachment-chip");
    await expect(chip).toHaveAttribute("data-attachment-status", "failed");
    await expect(chip).toHaveAttribute("data-attachment-failure", "upload_rejected");
    // The backend's own copy, not a status code paraphrased in the client.
    await expect(chip).toContainText("Attachments are limited to 10 MB.");
    // And no "try a clearer PDF" — nothing was stored, so that advice is wrong.
    await expect(chip).not.toContainText("clearer PDF");

    await page.locator("#chat-input-textarea").fill("what does this say?");
    await page.locator("#chat-send-btn").click();
    await expect.poll(() => recorded.message.length).toBe(1);
    // A failed upload has no id; grounding a turn on one would be inventing it.
    expect("attachment_id" in (recorded.message[0].body as object)).toBe(false);
  });

  test("an EXTRACT_FAILED row is a stored file we could not read", async ({ page }) => {
    await setupChat(page, {
      uploadResponse: (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            attachmentOut({
              extraction_status: "EXTRACT_FAILED",
              doc_type: "OTHER",
              doc_number: null,
              party_name: null,
              grand_total: null,
            })
          ),
        }),
    });
    await openChatWithSession(page);

    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);

    const chip = page.locator("#chat-attachment-chip");
    await expect(chip).toHaveAttribute("data-attachment-status", "failed");
    // Distinct from the rejection above: HTTP 200, a row exists, the file IS
    // stored — so the retry hint is the right one to show here and only here.
    await expect(chip).toHaveAttribute("data-attachment-failure", "extraction_failed");
    await expect(chip).toContainText("clearer PDF");
  });
});

test.describe("Feature 26 H12 — reload/reattach (§P2.6.6, decision D2)", () => {
  test("a refresh mid-conversation restores the attached document from the server", async ({
    page,
  }) => {
    const recorded = await setupChat(page);
    await openChatWithSession(page);
    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);
    await expect(page.locator("#chat-attachment-chip")).toHaveAttribute(
      "data-attachment-status",
      "ready"
    );

    await page.reload();
    // Re-open the conversation the way a user would.
    await page.locator(`#chat-session-${SESSION_ID}`).click();

    // Restored — and restored FROM THE SERVER, which is the fact that makes
    // decision D2 (persist a ChatAttachment row rather than session scratch)
    // worth anything. The client only remembered which id to ask about.
    await expect.poll(() => recorded.attachmentGet.length).toBeGreaterThan(0);
    expect(new URL(recorded.attachmentGet[0]).pathname).toBe(
      `/api/chat/attachments/${ATTACHMENT_ID}`
    );
    const chip = page.locator("#chat-attachment-chip");
    await expect(chip).toHaveAttribute("data-attachment-status", "ready");
    await expect(chip).toContainText("PO-4471");
  });

  test("a 404 on the remembered attachment clears it instead of showing an error", async ({
    page,
  }) => {
    await setupChat(page);
    await openChatWithSession(page);
    await page.locator('[data-testid="chat-attach-input"]').setInputFiles(PICKED_FILE);
    await expect(page.locator("#chat-attachment-chip")).toHaveAttribute(
      "data-attachment-status",
      "ready"
    );

    // The row is gone: swept by the TTL job (H8), or the session was deleted.
    await page.route("**/api/chat/attachments/*", (route) =>
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Attachment not found." }),
      })
    );
    await page.reload();
    await page.locator(`#chat-session-${SESSION_ID}`).click();

    await expect(page.locator("#chat-input-textarea")).toBeEnabled();
    await expect(page.locator("#chat-attachment-chip")).toHaveCount(0);
    // A stale pointer is not an incident — nothing is shown to the user.
    await expect(page.locator("text=Failed to load messages")).toHaveCount(0);
  });
});

test.describe("Feature 26 H12 — the JSON proxy routes exist in Next's router", () => {
  // WHAT THIS PROVES AND WHAT IT DOES NOT, stated because the distinction
  // matters: a 404 here would mean the route file is missing or misnamed (a
  // real and easy mistake with bracketed dynamic segments). Anything else means
  // Next matched the handler and ran it — at which point it tries to reach a
  // FastAPI backend that is not running in this environment, so the status it
  // returns says nothing about backend behaviour and nothing is asserted about
  // it. The upload route's own shape is covered for real above, through the UI.
  test("GET /api/chat/attachments/{id} is routed, not 404", async ({ request }) => {
    const res = await request.get(`/api/chat/attachments/${ATTACHMENT_ID}`);
    expect(res.status()).not.toBe(404);
  });

  test("POST /api/chat/attachments/{id}/confirm-matches is routed, not 404", async ({
    request,
  }) => {
    const res = await request.post(
      `/api/chat/attachments/${ATTACHMENT_ID}/confirm-matches`,
      { data: { invoice_ids: [] } }
    );
    expect(res.status()).not.toBe(404);
  });
});
