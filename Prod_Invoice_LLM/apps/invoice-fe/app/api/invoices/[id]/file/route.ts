// =============================================================================
// FILE: app/api/invoices/[id]/file/route.ts
// FEATURE: BE Gap 732 — replace the PDF on an invoice that has not been decided.
//
// REASON ADDED: there was no way to correct a wrongly uploaded file through the
//   API at all. Uploading the right one created a SECOND invoice and left the
//   wrong one in the queue (a key cannot delete), and the nearest workaround —
//   marking it REJECTED — wrote a false reason into the audit trail and fired
//   `invoice.rejected` at every subscriber, telling other systems a vendor had
//   been refused when the only mistake was the attached page.
//
// Multipart, so this mirrors `app/api/invoices/upload/route.ts` rather than
//   using `proxyJson`: the body is forwarded as FormData and the backend's
//   status and content type are passed back untouched. The 409 that a decided
//   invoice returns has to reach the caller intact — it is the difference
//   between "try again" and "ask an Admin to reopen it".
// =============================================================================
import { NextRequest, NextResponse } from "next/server";

import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/invoices/{id}/file → BE POST /invoices/{id}/file */
export async function POST(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  const formData = await request.formData();

  const response = await fetch(backendUrl(`/invoices/${params.id}/file`), {
    method: "POST",
    headers: await forwardedHeaders(request),
    body: formData,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json",
    },
  });
}
