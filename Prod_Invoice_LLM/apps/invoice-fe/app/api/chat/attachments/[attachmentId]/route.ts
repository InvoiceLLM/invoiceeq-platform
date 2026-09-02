// =============================================================================
// FILE: app/api/chat/attachments/[attachmentId]/route.ts
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H12,
//          spec §P2.6.7 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: the reload/reattach path. `useChatSession` re-reads the
//   attachment through here when a session is (re)opened, so a browser refresh
//   mid-conversation does not silently drop the document the next question is
//   grounded in. That path is the whole reason decision D2 persists a
//   `ChatAttachment` row instead of keeping the document in session scratch —
//   if the frontend never reads it back, D2 bought nothing.
//
// Backend: GET /api/v1/chat/attachments/{id} -> AttachmentOut, 404 when the id
//   is unknown OR belongs to another tenant (`_require_owned_attachment` returns
//   404 rather than 403 on purpose — confirming someone else's attachment
//   exists is itself a disclosure). The caller treats 404 as "forget it",
//   never as an error worth showing.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: { attachmentId: string } }
) {
  return proxyJson(request, `/chat/attachments/${params.attachmentId}`);
}
