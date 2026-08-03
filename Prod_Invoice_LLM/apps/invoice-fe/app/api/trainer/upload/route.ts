import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

// POST /api/trainer/upload -> backend /trainer/upload
// New-Vendor scope: forwards the multipart PDF upload untouched (fetch sets the
// multipart boundary itself, so no Content-Type is added).
export async function POST(request: NextRequest) {
  const formData = await request.formData();

  const response = await fetch(backendUrl("/trainer/upload"), {
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
