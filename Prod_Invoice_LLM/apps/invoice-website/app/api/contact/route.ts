import { NextRequest, NextResponse } from "next/server";
// Gap 350: `isValidIp`/`resolveClientIp` used to live in this file. They moved
// to lib/clientIp.ts unchanged when app/api/sandbox/keys/route.ts (a second
// public, rate-limited relay) needed the same trusted-IP answer. Behaviour here
// is identical — the functions were moved, not rewritten.
import { resolveClientIp } from "@/lib/clientIp";

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
 *   3. The resolved client IP is forwarded to the backend as `X-Client-IP` so the
 *      backend's own limiter has a key it can trust (see resolveClientIp below).
 */

const REQUIRED_FIELDS = ["name", "email", "message"] as const;

// In-memory rate limiting map: IP -> timestamp array.
//
// Gap 249 caveat, deliberate: this state is per-instance and this app scales
// 0..3 with scale-to-zero, so a cold start wipes it and the effective limit
// across instances is up to instanceCount x PROXY_MAX_REQUESTS. This layer is
// therefore best-effort edge shedding only — the authoritative limit is the
// backend's, which is Redis-backed and genuinely shared across replicas.
const proxyIpTimestamps = new Map<string, number[]>();
const PROXY_WINDOW_MS = 10 * 60 * 1000; // 10 minutes
const PROXY_MAX_REQUESTS = 5;
// Ceiling on tracked keys, so a caller rotating IPs cannot grow this Map
// without bound (a memory-exhaustion vector on the very endpoint being
// protected). Least-recently-touched keys are evicted first — Map preserves
// insertion order, and we re-insert on every touch.
const PROXY_MAX_TRACKED_IPS = 10_000;

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const cutoff = now - PROXY_WINDOW_MS;

  // Prune fully-expired keys on every check so idle entries cannot accumulate.
  // Collected first rather than deleted inline: this tsconfig targets below
  // ES2015, so directly iterating a Map is a compile error.
  const expired: string[] = [];
  proxyIpTimestamps.forEach((stamps: number[], key: string) => {
    if (!stamps.some((t: number) => t > cutoff)) expired.push(key);
  });
  expired.forEach((key) => proxyIpTimestamps.delete(key));

  const timestamps = (proxyIpTimestamps.get(ip) || []).filter((t) => t > cutoff);
  if (timestamps.length >= PROXY_MAX_REQUESTS) {
    proxyIpTimestamps.set(ip, timestamps);
    return true;
  }
  timestamps.push(now);
  // Delete-then-set moves the key to the end, making iteration order
  // least-recently-touched first for the eviction below.
  proxyIpTimestamps.delete(ip);
  proxyIpTimestamps.set(ip, timestamps);

  while (proxyIpTimestamps.size > PROXY_MAX_TRACKED_IPS) {
    const oldest = proxyIpTimestamps.keys().next();
    if (oldest.done) break;
    proxyIpTimestamps.delete(oldest.value);
  }
  return false;
}

export async function POST(request: NextRequest) {
  const backendApiUrl =
    process.env.BACKEND_API_URL || "http://localhost:8000";

  const clientIp = resolveClientIp(request);

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
    // This drops a real submission on the floor: the caller is told "received"
    // and nothing is ever persisted. That is intentional against bots, but a
    // password manager or aggressive autofill filling hp_field would silently
    // discard a genuine inquiry, and the user would never know.
    //
    // So log enough to recognise a false-positive pattern after the fact --
    // what filled the field, and who the submission claimed to be from. A real
    // person's submission looks like a plausible name/email with a value that
    // mirrors a visible field; a bot's is typically a URL or junk. This is a
    // WARN, not INFO, precisely so it is visible without hunting for it.
    //
    // The response below is deliberately unchanged (still a 201 with a fake
    // reference) -- differentiating it would tell a bot its filler was detected.
    console.warn(
      "[contact/route] Honeypot triggered — submission DISCARDED, not persisted.",
      JSON.stringify({
        ip: clientIp,
        hp_field_length: body.hp_field.trim().length,
        hp_field_sample: body.hp_field.trim().slice(0, 64),
        claimed_name:
          typeof body.name === "string" ? body.name.slice(0, 64) : null,
        claimed_email:
          typeof body.email === "string" ? body.email.slice(0, 128) : null,
        user_agent: request.headers.get("user-agent")?.slice(0, 200) || null,
      })
    );
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
        // Built explicitly, never spread from the incoming request: a
        // browser-supplied X-Client-IP must not survive this hop, since the
        // backend treats that header as our own attestation of the client IP.
        headers: {
          "Content-Type": "application/json",
          // Authoritative for the backend's limiter. The backend cannot derive
          // this itself — on its hop the platform-appended X-Forwarded-For entry
          // is this container's pod IP, which would bucket every website visitor
          // together. See routers/support.py::_get_client_ip.
          "X-Client-IP": clientIp,
          "X-Forwarded-For": clientIp,
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
