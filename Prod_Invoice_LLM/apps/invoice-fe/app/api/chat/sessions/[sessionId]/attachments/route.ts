// =============================================================================
// FILE: app/api/chat/sessions/[sessionId]/attachments/route.ts
// FEATURE: Feature 5 (chat) surface of BE Feature 26 Part 2 — task H12,
//          spec §P2.6.7 of apps/invoice-be/docs/feature_26_chat_attached_documents.md
//
// REASON ADDED: invoice-be's container-app ingress is `external: false` — the
//   browser cannot reach the backend directly, so every call goes through a
//   route handler here. Without this file `useChatSession.uploadAttachment()`
//   has nowhere to POST and the composer's paperclip (H10) is a control with no
//   destination.
//
// WHY THE BODY IS FORWARDED AS FormData RATHER THAN A STREAM:
//   This is a verbatim copy of the shape app/api/invoices/upload/route.ts has
//   used since Feature 3 — `await request.formData()` and hand the FormData
//   straight to fetch, which re-encodes it with its own boundary. §P2.6.7 asks
//   for exactly that ("do not hand-roll a different one"), and the reason is
//   concrete: forwarding `request.body` as a stream requires copying the
//   inbound Content-Type header *including its boundary parameter*, and getting
//   that subtly wrong produces a backend 422 that looks like a validation bug
//   rather than a proxy bug. The 10 MB cap (D3) bounds the buffering cost.
//
// WHY NO Content-Type IS PASSED TO forwardedHeaders():
//   fetch sets multipart/form-data plus the boundary itself when the body is a
//   FormData. Setting it explicitly would omit the boundary and break parsing.
//
// maxDuration: extraction runs SYNCHRONOUSLY inside this request
//   (`routers/chat_attachments.py::_extract_attachment` — a full Document
//   Intelligence round trip, then the H4 embed step), which is precisely why
//   AttachmentChip has a distinct "extracting" state. The platform default
//   would cut a slow scan off mid-extraction, so this route gets the same 120s
//   ceiling the chat message route already takes for the same class of reason.
// =============================================================================

import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

// POST /api/chat/sessions/[sessionId]/attachments
// Backend: POST /api/v1/chat/sessions/{id}/attachments (multipart, field "file").
// Returns AttachmentOut, or 409 (session full) / 415 (not a PDF) / 413 (>10 MB),
// each of which the chip renders as its `upload_rejected` failure with the
// backend's own `detail` string.
export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const formData = await request.formData();

  const response = await fetch(
    backendUrl(`/chat/sessions/${params.sessionId}/attachments`),
    {
      method: "POST",
      headers: await forwardedHeaders(request),
      body: formData,
      cache: "no-store",
      // Times out cleanly inside the 120s platform limit rather than tearing
      // the connection, so the XHR sees a 504 it can render instead of a bare
      // network error with no cause.
      signal: AbortSignal.timeout(110_000),
    }
  );

  const data = await response.text();
  return new NextResponse(data || null, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
