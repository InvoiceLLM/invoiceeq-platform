import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export async function POST(request: NextRequest) {
  const formData = await request.formData();

  const response = await fetch(backendUrl("/invoices/upload"), {
    method: "POST",
    headers: forwardedHeaders(request),
    body: formData,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
