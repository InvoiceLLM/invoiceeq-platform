// =============================================================================
// FILE: app/api/chat/attachments/[attachmentId]/confirm-matches/route.ts
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H12,
//          spec §P2.6.7 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: this proxies THE safety gate (D4). No financial answer is
//   produced for an attached document until the user has explicitly confirmed
//   which invoices it should be compared against; this is the call that records
//   that confirmation. `AttachmentMatchConfirm`'s confirm button reaches the
//   backend through here, via useChatSession.confirmMatches().
//
// Backend: POST /api/v1/chat/attachments/{id}/confirm-matches
//   body   {"invoice_ids": [uuid, ...]}
//   200    AttachmentOut with `confirmed_invoice_ids` populated
//   400    "Confirm at least one invoice." | "Only invoices offered as
//          candidates for this attachment can be confirmed."
//   404    unknown id, or another tenant's
//
// The 400s must reach the card intact — §P2.6.3's last bullet asks for exactly
// that — so this uses `proxyJson`, which forwards status and body verbatim
// rather than collapsing failures into a generic error.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { attachmentId: string } }
) {
  return proxyJson(request, `/chat/attachments/${params.attachmentId}/confirm-matches`);
}
