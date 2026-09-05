import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 20 / BE Feature 17: renders the invoice the builder would create,
 * without persisting anything.
 *
 * JSON in, `application/pdf` out — so this cannot use `proxyJson` (which reads
 * the body as text and would corrupt binary content). It follows
 * `app/api/invoices/[id]/pdf/route.ts` instead and streams the response body
 * straight through, preserving the backend's own content-type. That matters
 * for the error path: a 409 (duplicate number) comes back as JSON on the same
 * route, and the page distinguishes it from a PDF by content-type. (FE Gap 462
 * removed the 422 that used to share this route — the substitution renderer it
 * came from is deleted.)
 */
export async function POST(request: NextRequest) {
  const backendResponse = await fetch(backendUrl("/outbound-invoices/build/preview"), {
    method: "POST",
    headers: await forwardedHeaders(request, { "Content-Type": "application/json" }),
    body: await request.text(),
    cache: "no-store",
  });

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "Content-Type": backendResponse.headers.get("content-type") || "application/pdf",
    },
  });
}
