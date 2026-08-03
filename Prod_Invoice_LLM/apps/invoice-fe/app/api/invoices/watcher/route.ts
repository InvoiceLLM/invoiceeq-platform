import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const response = await fetch(backendUrl("/invoices/watcher/start"), {
    method: "POST",
    headers: { ...(await forwardedHeaders(request)), "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });

  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}
