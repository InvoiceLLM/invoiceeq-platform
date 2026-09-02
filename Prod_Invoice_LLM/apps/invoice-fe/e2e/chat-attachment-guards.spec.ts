// =============================================================================
// FILE: e2e/chat-attachment-guards.spec.ts
// FEATURE: BE Feature 26 Part 2, task H10 (§P2.6.1–P2.6.3) — the chat composer's
//          attachment guards and the copy the three new components render.
//
// WHY THESE ARE LOGIC TESTS AND NOT COMPONENT-RENDER TESTS — stated plainly
// rather than left for a reader to wonder about:
//   invoice-fe has exactly one test harness: @playwright/test. There is no
//   Jest, no vitest, no @testing-library (checked in package.json AND in
//   node_modules). Rendering AttachmentChip / AttachmentMatchConfirm inside a
//   spec via react-dom/server was tried and does not work: Playwright's own
//   babel transform rewrites JSX — in the spec file *and* in any .tsx it
//   imports — into its component-test object (`{__pw_type, type, props, key}`),
//   which react-dom rejects with "Objects are not valid as a React child".
//   So the assertions below run against the pure module those components
//   render from (lib/chatAttachments.ts), which is why that module exists.
//   DOM-level assertions on the two new components become possible once H11
//   (MessageBubble renders the confirmation card) and H12 (useChatSession
//   supplies the attachment state) make them reachable from /chat — at which
//   point they belong in a browser spec here, driven through the page.
//
// The one browser test at the bottom covers what IS reachable today: that the
// composer's DOM restructure did not break the existing input bar, and that the
// paperclip stays hidden until H12 wires a handler (rather than shipping a
// button that silently does nothing).
// =============================================================================

import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
  MAX_CHAT_ATTACHMENT_BYTES,
  MAX_CHAT_ATTACHMENTS_PER_SESSION,
  attachmentFailureHeadline,
  attachmentTierLabel,
  attachmentTruncationNotice,
  candidatesArePreChecked,
  docTypeBadgeLabel,
  isAttachmentLimitReached,
  truncateFilenameMiddle,
  validateChatAttachment,
} from "@/lib/chatAttachments";

const MB = 1024 * 1024;
const pdf = (sizeMb: number, name = "po.pdf") => ({ name, size: sizeMb * MB });

test.describe("Feature 26 H10 — composer attachment guards (§P2.6.1)", () => {
  test("a PDF within every cap is accepted", () => {
    expect(validateChatAttachment(pdf(3), { attachmentCount: 0 })).toBeNull();
  });

  test("a non-PDF is rejected on the suffix, case-insensitively", () => {
    expect(
      validateChatAttachment({ name: "scan.png", size: 1000 }, { attachmentCount: 0 })?.code
    ).toBe("wrong_type");
    // Uppercase extension is a real PDF and must pass — DropZone.tsx lowercases
    // before the endsWith check for exactly this reason.
    expect(
      validateChatAttachment({ name: "QUOTE.PDF", size: 1000 }, { attachmentCount: 0 })
    ).toBeNull();
  });

  test("the size cap is 10 MB, NOT DropZone's 25 MB", () => {
    // The specific defect §P2.6.1 warns about: a 25 MB client cap would let a
    // user wait through an upload the backend was always going to 413.
    expect(MAX_CHAT_ATTACHMENT_BYTES).toBe(10 * MB);
    expect(validateChatAttachment(pdf(20), { attachmentCount: 0 })?.code).toBe("too_large");
    // Boundary: exactly 10 MB is allowed (the backend rejects on `>`, not `>=`).
    expect(validateChatAttachment(pdf(10), { attachmentCount: 0 })).toBeNull();
    expect(
      validateChatAttachment({ name: "po.pdf", size: 10 * MB + 1 }, { attachmentCount: 0 })?.code
    ).toBe("too_large");
  });

  test("the per-session count cap is 5, and the paperclip disables at it", () => {
    expect(MAX_CHAT_ATTACHMENTS_PER_SESSION).toBe(5);
    expect(validateChatAttachment(pdf(1), { attachmentCount: 4 })).toBeNull();
    expect(validateChatAttachment(pdf(1), { attachmentCount: 5 })?.code).toBe("too_many");
    expect(isAttachmentLimitReached(4)).toBe(false);
    expect(isAttachmentLimitReached(5)).toBe(true);
  });

  test("a full session reports the count, not the file's other problems", () => {
    // Order matters: "you already have 5" is true whatever was picked, and
    // complaining about the type of a sixth file that could never be attached
    // sends the user off to find a PDF that will also be refused.
    const rejection = validateChatAttachment(
      { name: "scan.png", size: 40 * MB },
      { attachmentCount: 5 }
    );
    expect(rejection?.code).toBe("too_many");
  });

  test("the client caps still match the backend's constants", () => {
    // Drift protection, not decoration: these two numbers exist in two
    // languages, and a client cap that disagrees with the server produces
    // either a doomed upload or a file the user is refused for no visible
    // reason. Source of truth is the router itself.
    const routerPath = path.resolve(
      __dirname,
      "../../invoice-be/routers/chat_attachments.py"
    );
    const source = fs.readFileSync(routerPath, "utf8");
    expect(source).toContain("MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024");
    expect(source).toContain("MAX_ATTACHMENTS_PER_SESSION = 5");
    expect(source).toContain('ALLOWED_CONTENT_TYPES = {"application/pdf"}');
  });
});

test.describe("Feature 26 H10 — AttachmentChip copy (§P2.6.2)", () => {
  test("the two failure variants do not read the same", () => {
    const rejected = attachmentFailureHeadline("upload_rejected");
    const unreadable = attachmentFailureHeadline("extraction_failed");
    expect(rejected).not.toBe(unreadable);
    // The second must not imply nothing was stored — the file IS on the server.
    expect(unreadable.toLowerCase()).toContain("read");
  });

  test("the document-type badge is humanised, with a fallback", () => {
    expect(docTypeBadgeLabel("PURCHASE_ORDER")).toBe("PURCHASE ORDER");
    expect(docTypeBadgeLabel("quotation")).toBe("QUOTATION");
    expect(docTypeBadgeLabel(null)).toBe("DOCUMENT");
    expect(docTypeBadgeLabel("  ")).toBe("DOCUMENT");
  });

  test("long filenames truncate in the middle so the extension survives", () => {
    const long = "supplier-purchase-order-2026-quarter-three-final.pdf";
    const short = truncateFilenameMiddle(long);
    expect(short.length).toBeLessThan(long.length);
    expect(short.endsWith(".pdf")).toBe(true);
    expect(truncateFilenameMiddle("po.pdf")).toBe("po.pdf");
  });
});

test.describe("Feature 26 H10 — AttachmentMatchConfirm copy (§P2.6.3)", () => {
  test("each tier gets its own label, and a guess never reads like a join", () => {
    expect(attachmentTierLabel(1)).toBe("Matched on PO number");
    expect(attachmentTierLabel(2)).toBe("Matched on supplier and date");
    // Tier 3 is FORWARD-COMPATIBLE ONLY — find_candidate_invoices() returns
    // 1/2/0 today; the vector tier is E-4 / task H6 and is not built.
    expect(attachmentTierLabel(3)).toBe("Found by similarity — please confirm");
    expect(attachmentTierLabel(0)).toBe("No match found");
    const labels = [1, 2, 3, 0].map(attachmentTierLabel);
    expect(new Set(labels).size).toBe(4);
  });

  test("only a Tier-1 exact join is pre-checked", () => {
    expect(candidatesArePreChecked(1)).toBe(true);
    expect(candidatesArePreChecked(2)).toBe(false);
    expect(candidatesArePreChecked(3)).toBe(false);
  });

  test("the truncation notice appears only when the payload says truncated", () => {
    expect(attachmentTruncationNotice(20, false)).toBeNull();
    // The zero-candidate branch omits `truncated` entirely.
    expect(attachmentTruncationNotice(0, undefined)).toBeNull();
    const notice = attachmentTruncationNotice(20, true);
    expect(notice).toContain("20");
    // Tier 3's cap is 10 (E-4); the count comes from the payload, so the copy
    // needs no change when that tier lands.
    expect(attachmentTruncationNotice(10, true)).toContain("10");
  });
});

// UPDATED BY TASK H12 (2026-09-02). This block asserted that the paperclip was
// ABSENT from /chat, which was correct while page.tsx supplied no `onAttach` —
// H10 shipped the control deliberately dark rather than dead. H12 wires
// useChatSession's `uploadAttachment` through app/chat/page.tsx, so the render
// gate is now satisfied and the old assertion asserts the opposite of the
// product's intended behaviour.
//
// The gate itself (`{onAttach && ...}` in ChatWindow) is unchanged in the code
// but is no longer exercised by any rendered surface: /chat is ChatWindow's
// only consumer (/help renders SupportChatWindow, a different component) and it
// now supplies a handler. Stated rather than left as an implied loss of
// coverage. The full upload flow lives in e2e/chat-attachment-upload.spec.ts.
test.describe("Feature 26 H10 — the composer still works; H12 lit the paperclip", () => {
  test("the chat composer renders, and the paperclip is now present (H12)", async ({
    page,
  }) => {
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
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
    );

    await page.goto("/chat");

    // The composer survived the container restructure (the chip now sits above
    // the flex row, so the row it lives in is a new nested div).
    await expect(page.locator("#chat-input-textarea")).toBeVisible();
    await expect(page.locator("#chat-send-btn")).toBeVisible();

    // H12: page.tsx now supplies `onAttach`, so the control renders. It is
    // DISABLED here because this test opens /chat with no session selected —
    // the same condition that disables the send button — which is the correct
    // state, not a dead button.
    await expect(page.locator("#chat-attach-btn")).toBeVisible();
    await expect(page.locator("#chat-attach-btn")).toBeDisabled();
    // Nothing attached yet, so no chip.
    await expect(page.locator("#chat-attachment-chip")).toHaveCount(0);
  });
});
