import { NextRequest, NextResponse } from "next/server";

/**
 * Public pass-through for SendGrid Inbound Parse → BE mailintegration.
 *
 * Why this exists: `invoice-be`'s Container App ingress is `external: false`,
 * so SendGrid (public internet) can never POST to the backend's own
 * `/api/v1/email/mailintegration`. `invoice-website` is the only public
 * origin — same topology as PayU (`app/api/v1/billing/payu/relay.ts`).
 *
 * Path shape matches the backend exactly so SendGrid's Destination URL is
 * `{websiteFqdn}/api/v1/email/mailintegration` with no BE URL-shape change.
 *
 * Deliberately UNAUTHENTICATED — SendGrid has no Clerk session. An `auth()`
 * gate would drop every inbound mail. Authenticity hardening (shared secret /
 * signed headers) remains Gap 124; until then this is open like PayU was
 * before hash verify, and the BE already drops unknown From addresses.
 *
 * Multipart must be forwarded as raw bytes + original Content-Type (boundary
 * intact). Re-parsing with `formData()` and re-serializing corrupts PDF parts.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const backendApiUrl = process.env.BACKEND_API_URL;
  if (!backendApiUrl) {
    console.error("BACKEND_API_URL is not set — cannot relay mailintegration.");
    return NextResponse.json(
      {
        success: false,
        status: "relay_error",
        message: "BACKEND_API_URL is not configured on invoice-website.",
      },
      { status: 502 }
    );
  }

  const contentType = request.headers.get("content-type") || "";
  let body: ArrayBuffer;
  try {
    body = await request.arrayBuffer();
  } catch (e) {
    console.error("Failed to read mailintegration request body:", e);
    return NextResponse.json(
      { success: false, status: "relay_error", message: "Could not read request body." },
      { status: 400 }
    );
  }

  const target = `${backendApiUrl.replace(/\/$/, "")}/api/v1/email/mailintegration`;

  let response: Response;
  try {
    response = await fetch(target, {
      method: "POST",
      headers: {
        ...(contentType ? { "Content-Type": contentType } : {}),
      },
      body,
      cache: "no-store",
    });
  } catch (e) {
    console.error("mailintegration relay to backend failed:", e);
    return NextResponse.json(
      {
        success: false,
        status: "relay_error",
        message: "Could not reach invoice-be mailintegration endpoint.",
      },
      { status: 502 }
    );
  }

  const responseBody = await response.arrayBuffer();
  const responseType = response.headers.get("content-type") || "application/json";
  return new NextResponse(responseBody, {
    status: response.status,
    headers: { "Content-Type": responseType },
  });
}
