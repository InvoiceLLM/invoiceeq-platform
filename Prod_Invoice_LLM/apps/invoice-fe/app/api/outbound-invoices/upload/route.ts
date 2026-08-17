import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const formData = await request.formData();

  const response = await fetch(backendUrl("/outbound-invoices/upload"), {
    method: "POST",
    headers: await forwardedHeaders(request),
    body: formData,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
