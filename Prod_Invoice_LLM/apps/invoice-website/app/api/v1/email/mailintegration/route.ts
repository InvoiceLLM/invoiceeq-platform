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
 * Deliberately UNAUTHENTICATED at *this* hop — SendGrid has no Clerk session,
 * so an `auth()` gate would drop every inbound mail. Authenticity is enforced
 * one hop later, by the backend, against the `INBOUND_PARSE_SHARED_SECRET`
 * shared secret (Gap 124 item 5). This route's job is to carry that secret
 * through unchanged, which means preserving the two places it can live:
 *
 *   - the **query string** (`?key=…` / `?secret=…`), because a SendGrid
 *     Inbound Parse Destination URL is the only thing configurable in their
 *     dashboard — there is no signing key and no signature header;
 *   - the **Authorization / X-Inbound-Secret headers**, for Basic credentials
 *     embedded in that same Destination URL or for our own tooling.
 *
 * Both were previously dropped on the floor here (only Content-Type was
 * forwarded), so enforcing the secret in the backend without this change would
 * have rejected 100% of real inbound mail.
 *
 * Multipart must be forwarded as raw bytes + original Content-Type (boundary
 * intact). Re-parsing with `formData()` and re-serializing corrupts PDF parts.
 */

export const dynamic = "force-dynamic";

/**
 * Gap 124 item 7. Mirrors the backend's INBOUND_EMAIL_MAX_BYTES default so an
 * oversized body is refused at the public edge, before it is buffered into
 * this process's memory by `arrayBuffer()` and pushed across to the backend.
 * The backend enforces the same cap independently — it is the real boundary;
 * this one only stops the relay itself being the resource sink.
 */
const MAX_INBOUND_BYTES = 25 * 1024 * 1024;

/** Headers that may carry the shared secret, forwarded verbatim when present. */
const SECRET_HEADERS = ["authorization", "x-inbound-secret", "x-sendgrid-inbound-secret"];

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

  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_INBOUND_BYTES) {
    console.warn(
      `Refusing oversized mailintegration POST: ${declaredLength} bytes > ${MAX_INBOUND_BYTES}.`
    );
    return NextResponse.json(
      {
        success: false,
        status: "too_large",
        message: `Inbound email exceeds the ${MAX_INBOUND_BYTES} byte limit.`,
      },
      { status: 413 }
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

  // Re-check against what actually arrived: a chunked POST carries no
  // Content-Length for the guard above to read.
  if (body.byteLength > MAX_INBOUND_BYTES) {
    console.warn(
      `Refusing oversized mailintegration POST: ${body.byteLength} bytes > ${MAX_INBOUND_BYTES}.`
    );
    return NextResponse.json(
      {
        success: false,
        status: "too_large",
        message: `Inbound email exceeds the ${MAX_INBOUND_BYTES} byte limit.`,
      },
      { status: 413 }
    );
  }

  // Query string preserved: it is where a SendGrid Destination URL carries the
  // shared secret.
  const target =
    `${backendApiUrl.replace(/\/$/, "")}/api/v1/email/mailintegration` +
    request.nextUrl.search;

  const forwardedHeaders: Record<string, string> = {
    ...(contentType ? { "Content-Type": contentType } : {}),
  };
  for (const name of SECRET_HEADERS) {
    const value = request.headers.get(name);
    if (value) forwardedHeaders[name] = value;
  }

  let response: Response;
  try {
    response = await fetch(target, {
      method: "POST",
      headers: forwardedHeaders,
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
