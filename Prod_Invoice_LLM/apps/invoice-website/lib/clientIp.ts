import type { NextRequest } from "next/server";

/**
 * Gap 249 / Gap 350: resolve the client IP for rate limiting, trusting only
 * values our own infrastructure produced.
 *
 * MOVED HERE VERBATIM from `app/api/contact/route.ts` (Gap 350), where it was
 * the only copy. It is shared now because `app/api/sandbox/keys/route.ts` is a
 * second public, unauthenticated, rate-limited relay and needs the *same*
 * answer to "which IP claim can this platform trust". Two independently
 * maintained copies of this function is exactly the drift the backend refused
 * when it reused `routers/support.py::_get_client_ip` for the sandbox limiter
 * rather than writing a second one (BE Feature 25 / Gap 340, constraint 5).
 *
 * The logic below is unchanged from the Gap 249 version — only its location is
 * new. The original reasoning, kept in full:
 *
 * This previously took `x-forwarded-for.split(",")[0]` — the leftmost entry —
 * which is exactly the one the client controls. A proxy *appends* the peer it
 * actually saw to the right of whatever arrived, so the leftmost element is
 * just the first hop's unverified claim: sending a fresh value per request
 * reset the window every time, on both this limiter and the backend's.
 *
 * Topology this is written against (verified against infra/, not assumed):
 * this app is the internet edge — `invoice-website.bicep` sets
 * `ingress.external: true`, and Container Apps' Envoy ingress runs with
 * `use_remote_address`, so it appends the real connection peer to
 * X-Forwarded-For. The rightmost entry is therefore the platform's own
 * observation. Rightmost is also the safer read under uncertainty: if the
 * platform appends, it is the true peer; if it replaced the header wholesale,
 * rightmost === leftmost === the true peer either way.
 *
 * Azure Front Door (infra/modules/network/front-door.bicep) is NOT in the path
 * today — it is gated on the `customDomainName` param, which is unset, and has
 * never been deployed. Once it is, the rightmost XFF entry becomes a Front Door
 * edge IP (which would bucket all traffic together), so the FRONT_DOOR_ID
 * branch below takes over. It stays inert until that env var is set to the real
 * profile GUID, because X-Azure-ClientIP is forgeable by anyone who can reach
 * this app directly; honouring it unconditionally would just be a new bypass.
 */
export function isValidIp(value: string | null | undefined): string | null {
  if (!value) return null;
  let candidate = value.trim();
  // Tolerate "host:port" (IPv4) and "[::1]:443" (IPv6) forms.
  if (candidate.startsWith("[")) {
    candidate = candidate.slice(1).split("]")[0];
  } else if ((candidate.match(/:/g) || []).length === 1) {
    candidate = candidate.split(":")[0];
  }
  const ipv4 =
    /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
  // Deliberately loose IPv6 shape check — this only needs to reject junk so it
  // cannot become an unbounded rate-limit key, not to validate addresses.
  const ipv6 = /^[0-9a-fA-F:]+$/;
  if (ipv4.test(candidate)) return candidate;
  if (candidate.includes(":") && ipv6.test(candidate)) return candidate.toLowerCase();
  return null;
}

export function resolveClientIp(request: NextRequest): string {
  // 1. Front Door, only when deployed and only when the request proves it came
  //    through our profile (Front Door overwrites X-Azure-FDID on every request).
  const expectedFdid = (process.env.FRONT_DOOR_ID || "").trim();
  if (
    expectedFdid &&
    (request.headers.get("x-azure-fdid") || "").trim() === expectedFdid
  ) {
    const fdIp = isValidIp(request.headers.get("x-azure-clientip"));
    if (fdIp) return fdIp;
  }

  // 2. Rightmost X-Forwarded-For entry — the hop the platform observed.
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    const parts = forwardedFor.split(",");
    for (let i = parts.length - 1; i >= 0; i--) {
      const parsed = isValidIp(parts[i]);
      if (parsed) return parsed;
    }
  }

  // 3. No trustworthy source. X-Real-IP is deliberately not consulted: nothing
  //    in our path sets it that does not also set X-Forwarded-For, and it is
  //    trivially forgeable. Local dev (no proxy headers at all) lands here and
  //    shares a single bucket, which is correct for a single-developer machine.
  return "unknown";
}
