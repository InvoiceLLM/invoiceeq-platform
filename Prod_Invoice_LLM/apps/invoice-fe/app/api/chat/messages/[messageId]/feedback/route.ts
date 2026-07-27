// =============================================================================
// FILE: app/api/chat/messages/[messageId]/feedback/route.ts
// FEATURE: Gap 54 — per-answer chat feedback (thumbs up/down)
// REASON ADDED: MessageBubble's FeedbackVote component needs a same-origin
//   proxy to PUT/DELETE be_features_tracker.md Gap 54's
//   PUT|DELETE /chat/messages/{message_id}/feedback endpoint, matching every
//   other route in this app going through app/api/** rather than calling the
//   backend directly from the browser.
// =============================================================================

import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export async function PUT(
  request: NextRequest,
  { params }: { params: { messageId: string } }
) {
  return proxyJson(request, `/chat/messages/${params.messageId}/feedback`);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { messageId: string } }
) {
  return proxyJson(request, `/chat/messages/${params.messageId}/feedback`);
}
