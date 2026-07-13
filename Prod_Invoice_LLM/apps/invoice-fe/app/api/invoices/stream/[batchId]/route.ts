import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, { params }: { params: { batchId: string } }) {
  const backendResponse = await fetch(backendUrl(`/invoices/stream/${params.batchId}`), {
    method: "GET",
    headers: forwardedHeaders(request),
    cache: "no-store",
  });

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
