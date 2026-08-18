import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Feature Website 5: Contact Us page API proxy.
 *
 * Website path : /api/contact
 * Backend path : /api/v1/support/contact
 *
 * This is a PUBLIC, unauthenticated endpoint — it mirrors the
 * /auth/provision pattern (also unauthenticated), forwarding the
 * browser's JSON body to the backend.
 *
 * The backend has internal-only ingress in Azure (invoice-be.bicep sets
 * ingress.external: false), so the browser can never reach it directly.
 * This server-side proxy bridges the gap, keeping the backend origin
 * out of the client bundle.
 *
 * Rate-limiting & abuse prevention:
 *   1. Honeypot check: `hp_field` must be empty (hidden to humans, filled by bots).
 *   2. Proxy rate limit: in-memory sliding window, max 5 submissions per 10 minutes per IP.
 *   3. Client IP is forwarded via `X-Forwarded-For` / `X-Real-IP` so backend
 *      rate limiting can also track distinct origin IPs.
 */

const REQUIRED_FIELDS = ["name", "email", "message"] as const;

// In-memory rate limiting map: IP -> timestamp array
const proxyIpTimestamps = new Map<string, number[]>();
const PROXY_WINDOW_MS = 10 * 60 * 1000; // 10 minutes
const PROXY_MAX_REQUESTS = 5;

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const cutoff = now - PROXY_WINDOW_MS;
  const timestamps = (proxyIpTimestamps.get(ip) || []).filter((t) => t > cutoff);
  if (timestamps.length >= PROXY_MAX_REQUESTS) {
    proxyIpTimestamps.set(ip, timestamps);
    return true;
  }
  timestamps.push(now);
  proxyIpTimestamps.set(ip, timestamps);
  return false;
}

export async function POST(request: NextRequest) {
  const backendApiUrl =
    process.env.BACKEND_API_URL || "http://localhost:8000";

  // Extract client IP for rate limiting and backend forwarding
  const forwardedFor = request.headers.get("x-forwarded-for");
  const realIp = request.headers.get("x-real-ip");
  const clientIp = forwardedFor ? forwardedFor.split(",")[0].trim() : (realIp || "unknown");

  if (isRateLimited(clientIp)) {
    console.warn(`[contact/route] Rate limit exceeded for IP: ${clientIp}`);
    return NextResponse.json(
      { detail: "Too many requests. Please wait a few minutes before submitting again." },
      { status: 429, headers: { "Retry-After": "600" } }
    );
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Invalid JSON body" },
      { status: 400 }
    );
  }

  // Honeypot check — bots that auto-fill all form fields will populate hp_field
  if (typeof body.hp_field === "string" && body.hp_field.trim() !== "") {
    console.info(`[contact/route] Honeypot triggered from IP: ${clientIp}`);
    // Silently return success to waste bot resources without touching backend/SendGrid
    return NextResponse.json(
      {
        success: true,
        ticket_number: "REF-FILTERED",
        message: "Your inquiry has been received. Thank you.",
        email_dispatched: false,
      },
      { status: 201 }
    );
  }

  // Basic envelope validation — the backend validates more strictly
  for (const field of REQUIRED_FIELDS) {
    const val = (body[field] as string | undefined)?.trim();
    if (!val) {
      return NextResponse.json(
        { detail: `${field} is required` },
        { status: 422 }
      );
    }
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${backendApiUrl}/api/v1/support/contact`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Forwarded-For": clientIp,
          "X-Real-IP": clientIp,
        },
        body: JSON.stringify(body),
      }
    );
  } catch (err) {
    console.error("[contact/route] backend unreachable:", err);
    return NextResponse.json(
      { detail: "Support service temporarily unavailable. Please try again shortly." },
      { status: 503 }
    );
  }

  const data = await backendRes.json().catch(() => ({}));

  if (!backendRes.ok) {
    console.error(
      "[contact/route] backend returned %d: %o",
      backendRes.status,
      data
    );
    return NextResponse.json(
      { detail: data?.detail || "Failed to submit inquiry. Please try again." },
      { status: backendRes.status }
    );
  }

  return NextResponse.json(data, { status: backendRes.status });
}
