import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/trainer/sessions/{id}/pdf -> backend /trainer/sessions/{id}/pdf
 *
 * The one genuinely new piece of FE plumbing in Feature 14, and it is deliberately
 * a binary stream rather than `proxyJson`: this returns a PDF body, and reading it
 * through `response.text()` would corrupt it.
 *
 * Why it exists: a Trainer *upload* creates no `Invoice` row (that would consume
 * the tenant's free-invoice quota and put a training sample on the dashboard), so
 * its document cannot be served from `/api/invoices/{id}/pdf`. Before this, the FE
 * held a client-side `URL.createObjectURL()` for the file it had just uploaded —
 * which survived neither a page reload nor opening the session on another device,
 * on a screen whose entire job is "look at the alert next to the document that
 * caused it". `_session_pdf_url()` now returns this path for upload-path sessions
 * and `/api/invoices/{id}/pdf` for history-path ones.
 *
 * Mirrors `app/api/invoices/[id]/pdf/route.ts` exactly, including passing
 * `backendResponse.body` straight through rather than buffering it.
 */
export async function GET(request: NextRequest, { params }: { params: { id: string } }) {
  const backendResponse = await fetch(backendUrl(`/trainer/sessions/${params.id}/pdf`), {
    method: "GET",
    headers: await forwardedHeaders(request),
    cache: "no-store",
  });

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "Content-Type": backendResponse.headers.get("content-type") || "application/pdf",
    },
  });
}
