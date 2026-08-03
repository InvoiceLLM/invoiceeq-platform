import { NextRequest, NextResponse } from "next/server";
import { backendUrl, forwardedHeaders } from "@/lib/backendProxy";

// POST /api/trainer/sessions/global -> backend /trainer/sessions/global
// Global scope: multipart, but the sample PDF is OPTIONAL (chat-only sessions send
// an empty FormData). Forwarded as multipart so the backend's File(None) param works.
export async function POST(request: NextRequest) {
  const formData = await request.formData();

  const response = await fetch(backendUrl("/trainer/sessions/global"), {
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
