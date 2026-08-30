import { NextRequest, NextResponse } from "next/server";
import { resolveClientIp } from "@/lib/clientIp";

export const dynamic = "force-dynamic";

/**
 * Website Gap 350 — sandbox API key issuance relay.
 *
 * Website path : POST /api/sandbox/keys
 * Backend path : POST /api/v1/sandbox/keys   (BE Feature 25 / Gap 340)
 *
 * WHY A RELAY AND NOT A DIRECT BROWSER CALL
 * -----------------------------------------
 * `invoice-be.bicep` sets `ingress.external: false`, so the backend has no
 * public ingress in any deployed environment — a browser can reach it on
 * localhost and nowhere else. Every other backend call this app makes goes
 * through a server-side route handler for exactly that reason
 * (`/api/auth/provision`, Gap 7; `/api/contact`, Feature 5; the PayU return
 * relays, Feature 3). This is the same pattern, not a new one. It also keeps
 * `BACKEND_API_URL` out of the client bundle.
 *
 * THIS ENDPOINT IS PUBLIC AND UNAUTHENTICATED, and what it relays hands the
 * caller a real (throwaway, readonly, TTL'd) credential. It is therefore
 * modelled on `/api/contact` — the app's only other anonymous relay — rather
 * than on `/api/auth/provision`:
 *
 *   1. Best-effort in-memory sliding-window limit per resolved client IP, so an
 *      obvious loop is shed at the edge before it reaches the backend at all.
 *   2. The resolved IP is forwarded as `X-Client-IP`, because the backend
 *      cannot derive it itself — on its hop the platform-appended
 *      X-Forwarded-For entry is *this container's* pod IP, which would bucket
 *      every website visitor into one limiter key. See
 *      `routers/support.py::_get_client_ip`, which `routers/sandbox.py` reuses.
 *   3. The authoritative limit is still the backend's (Redis-backed, shared
 *      across replicas, 3/hour by default) plus its global unclaimed-tenant
 *      cap. This layer is edge shedding, not the control.
 *
 * ITS OWN RATE-LIMIT BUCKET, DELIBERATELY. The map below is separate from the
 * contact form's for the same reason `routers/sandbox.py` gave its limiter its
 * own Redis key prefix: both key on the bare IP, so a shared namespace would
 * make a visitor's contact-form submissions eat their sandbox allowance.
 *
 * `SANDBOX_KEYS_ENABLED` IS FALSE BY DEFAULT ON THE BACKEND, and there is no
 * public endpoint anywhere that reports its value — checked, not assumed:
 * `main.py` exposes only `/`, `/health`, `/health/liveness` and
 * `/health/readiness`, none of which mention it, and `routers/sandbox.py`
 * `_require_sandbox_enabled()` 404s the whole surface when it is off (404 not
 * 403, so a disabled deployment looks like one without the feature). The only
 * way to learn the flag's state is to make the call, so this handler translates
 * that 404 into an explicit, machine-readable `code: "sandbox_disabled"` with a
 * 503, and the CTA renders a plain "not available yet" instead of a raw error.
 */

const PROXY_WINDOW_MS = 60 * 60 * 1000; // 1 hour, matching SANDBOX_ISSUE_RATE_WINDOW_SECONDS
const PROXY_MAX_REQUESTS = 3; // matching SANDBOX_ISSUE_RATE_LIMIT
const PROXY_MAX_TRACKED_IPS = 10_000;

const sandboxIpTimestamps = new Map<string, number[]>();

/**
 * Same shape as the contact relay's limiter and with the same caveat: this
 * state is per-instance and this app scales 0..3 with scale-to-zero, so a cold
 * start wipes it and the effective ceiling across instances is up to
 * instanceCount x PROXY_MAX_REQUESTS. Best-effort only, by construction.
 */
function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const cutoff = now - PROXY_WINDOW_MS;

  // Collected first rather than deleted inline: this tsconfig targets below
  // ES2015, so directly iterating a Map is a compile error.
  const expired: string[] = [];
  sandboxIpTimestamps.forEach((stamps: number[], key: string) => {
    if (!stamps.some((t: number) => t > cutoff)) expired.push(key);
  });
  expired.forEach((key) => sandboxIpTimestamps.delete(key));

  const timestamps = (sandboxIpTimestamps.get(ip) || []).filter((t) => t > cutoff);
  if (timestamps.length >= PROXY_MAX_REQUESTS) {
    sandboxIpTimestamps.set(ip, timestamps);
    return true;
  }
  timestamps.push(now);
  // Delete-then-set moves the key to the end, making iteration order
  // least-recently-touched first for the eviction below.
  sandboxIpTimestamps.delete(ip);
  sandboxIpTimestamps.set(ip, timestamps);

  while (sandboxIpTimestamps.size > PROXY_MAX_TRACKED_IPS) {
    const oldest = sandboxIpTimestamps.keys().next();
    if (oldest.done) break;
    sandboxIpTimestamps.delete(oldest.value);
  }
  return false;
}

export async function POST(request: NextRequest) {
  const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";
  const clientIp = resolveClientIp(request);

  if (isRateLimited(clientIp)) {
    console.warn(`[sandbox/keys] edge rate limit exceeded for IP: ${clientIp}`);
    return NextResponse.json(
      {
        detail:
          "Too many sandbox keys requested from this address. Try again later, " +
          "or start a free trial instead.",
        code: "rate_limited",
      },
      { status: 429, headers: { "Retry-After": "3600" } }
    );
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(`${backendApiUrl.replace(/\/$/, "")}/api/v1/sandbox/keys`, {
      method: "POST",
      // SECURITY-CRITICAL, and the reason this object is a fresh literal rather
      // than anything derived from `request.headers`.
      //
      // `routers/support.py::_get_client_ip` — which `routers/sandbox.py`
      // reuses — trusts `X-Client-IP` AHEAD of `X-Forwarded-For`, because that
      // header is this app's own attestation of who the caller is. The backend
      // cannot derive it itself: on its hop the platform-appended XFF entry is
      // this container's pod IP, which would bucket every website visitor into
      // one limiter key.
      //
      // That trust is only sound while every caller builds the header from a
      // trusted source. A generic pass-through here — spreading the incoming
      // headers, or copying the caller's `X-Client-IP`/`X-Forwarded-For` —
      // would let a browser send a fresh random value per request and defeat
      // the backend's per-IP limit entirely, leaving only the global unclaimed
      // cap (`SANDBOX_MAX_UNCLAIMED_TENANTS`, 500) between an attacker and
      // permanent exhaustion of sandbox issuance for everyone. That cap is
      // *not* a sufficient backstop today: BE Gap 340 records that no ACA Job
      // schedules `scripts/sweep_sandbox_tenants.py`, so exhausted capacity is
      // not reclaimed on any timetable.
      //
      // So: both headers are OVERWRITTEN with the server-resolved value, and
      // the incoming `x-client-ip` is never read anywhere in this file.
      // `resolveClientIp()` itself reads only the *rightmost* X-Forwarded-For
      // entry (the hop our own Envoy ingress observed and appended) or a
      // Front-Door-verified `X-Azure-ClientIP` — never a client-controlled
      // leftmost claim. See lib/clientIp.ts and Gap 249.
      headers: {
        "Content-Type": "application/json",
        "X-Client-IP": clientIp,
        "X-Forwarded-For": clientIp,
      },
      // The backend endpoint takes no body. Sending "{}" rather than nothing
      // keeps the Content-Type header honest.
      body: "{}",
      cache: "no-store",
    });
  } catch (err) {
    console.error("[sandbox/keys] backend unreachable:", err);
    return NextResponse.json(
      {
        detail:
          "The sandbox service is unreachable right now. Please try again shortly.",
        code: "unreachable",
      },
      { status: 503 }
    );
  }

  const data = (await backendRes.json().catch(() => ({}))) as {
    detail?: string;
    api_key?: string;
  };

  if (backendRes.status === 404) {
    // The feature flag is off (or the router is not mounted at all — the same
    // observable state, and the same honest answer either way). Deliberately
    // not passed through as a 404: a 404 from a route the browser just called
    // reads as "this website is broken", which is the wrong story.
    console.warn(
      "[sandbox/keys] backend returned 404 — SANDBOX_KEYS_ENABLED is off, " +
        "or routers/sandbox.py is not mounted in this deployment."
    );
    return NextResponse.json(
      {
        detail:
          "Sandbox keys aren't switched on yet. Start a free trial and you'll " +
          "get a real workspace and API key immediately.",
        code: "sandbox_disabled",
      },
      { status: 503 }
    );
  }

  if (!backendRes.ok) {
    console.error("[sandbox/keys] backend returned %d: %o", backendRes.status, data);
    return NextResponse.json(
      {
        detail:
          data?.detail ||
          "Couldn't issue a sandbox key right now. Please try again shortly.",
        code: backendRes.status === 429 ? "rate_limited" : "error",
      },
      { status: backendRes.status }
    );
  }

  // Passed through verbatim on success — the body carries the raw `api_key`,
  // which is shown exactly once and is never logged here (the same shown-once
  // contract `/api/auth/provision` and Settings -> Security key rotation use).
  return NextResponse.json(data, { status: backendRes.status });
}
