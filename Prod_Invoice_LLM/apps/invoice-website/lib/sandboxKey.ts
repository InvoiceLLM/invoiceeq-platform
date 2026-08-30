/**
 * Website Gap 350 — the one piece of state that connects "an anonymous visitor
 * took a sandbox key on the homepage" to "that same visitor later signed up for
 * real", so `POST /api/sandbox/claim` can promote their trial workspace instead
 * of a brand-new empty tenant being created and the trial data abandoned.
 *
 * WHY localStorage
 * ----------------
 * The two events are minutes-to-days apart, on different routes, with no server
 * session in between — the visitor is anonymous when the key is issued, by
 * definition (`POST /api/v1/sandbox/keys` takes no auth). So the only place the
 * link can live is the visitor's own browser.
 *
 * localStorage rather than a cookie, deliberately: the claim is initiated by
 * client-side code on /signup, so the value never needs to reach a server on
 * its own, and a cookie would then be sent on every request to this origin for
 * no reason. Same-origin storage also means `invoicellm.admsofttech.com`'s
 * homepage and its /signup page share it, which is the whole requirement.
 *
 * WHAT IS BEING STORED, honestly: a live credential. It is a deliberately weak
 * one — `readonly` scope pinned three ways on the backend, a fresh throwaway
 * tenant containing only what this same visitor put in it, a hard TTL
 * (`SANDBOX_KEY_TTL_HOURS`, 72h default) enforced on every authentication, and
 * a chat/invoice meter. The realistic worst case of it leaking is that someone
 * reads the visitor's own uploaded sample invoice. Not storing it at all would
 * make the claim path impossible, which is the feature.
 *
 * EVERY ACCESS IS GUARDED. localStorage throws outright in some Safari private
 * modes and when site data is blocked; none of that may break the page, so
 * every function here returns a safe value instead of propagating.
 */

const STORAGE_KEY = "invoiceeq.sandbox_key.v1";

export interface StoredSandboxKey {
  /** The raw `inv_test_...` key. */
  apiKey: string;
  /** The sandbox tenant's id — carried for support/diagnostics only. */
  tenantId: string;
  /** ISO-8601, straight from the backend's `expires_at`. */
  expiresAt: string;
}

function isExpired(expiresAt: string): boolean {
  const ts = Date.parse(expiresAt);
  // An unparseable timestamp is treated as expired rather than as "never
  // expires": a value we cannot reason about must not keep a credential alive.
  if (Number.isNaN(ts)) return true;
  return ts <= Date.now();
}

export function storeSandboxKey(value: StoredSandboxKey): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch (err) {
    // Non-fatal: the visitor still got their key on screen, they just will not
    // get the automatic claim at signup. Warn so it is diagnosable.
    console.warn("[sandbox] could not persist the sandbox key locally:", err);
  }
}

/**
 * Returns the stored key, or null if there is none, it is malformed, or it has
 * already expired. An expired entry is also *removed* on read — leaving it
 * behind would mean every subsequent signup attempts a claim that can only
 * ever 410.
 */
export function readStoredSandboxKey(): StoredSandboxKey | null {
  if (typeof window === "undefined") return null;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<StoredSandboxKey>;
    if (
      typeof parsed?.apiKey !== "string" ||
      !parsed.apiKey ||
      typeof parsed?.expiresAt !== "string"
    ) {
      clearStoredSandboxKey();
      return null;
    }
    if (isExpired(parsed.expiresAt)) {
      clearStoredSandboxKey();
      return null;
    }
    return {
      apiKey: parsed.apiKey,
      tenantId: typeof parsed.tenantId === "string" ? parsed.tenantId : "",
      expiresAt: parsed.expiresAt,
    };
  } catch {
    clearStoredSandboxKey();
    return null;
  }
}

export function clearStoredSandboxKey(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing useful to do — a key we cannot clear will expire on its own.
  }
}

/**
 * Website-side mirror of the backend's `SANDBOX_KEYS_ENABLED`, which defaults
 * to False and is False in every environment today.
 *
 * A mirror is not ideal and is not pretended to be. There is no public
 * config/status endpoint on the backend that reports the flag — verified by
 * reading `main.py` (only `/`, `/health`, `/health/liveness`,
 * `/health/readiness` are public) and `routers/sandbox.py`, whose
 * `_require_sandbox_enabled()` 404s the entire surface when it is off. The only
 * way to *ask* is to call the issuance endpoint, and that call has side effects
 * (it mints a tenant, and it consumes the visitor's 3-per-hour allowance), so
 * it cannot be used as a probe.
 *
 * So there are two layers, and the second one is what makes the first safe to
 * get wrong:
 *   1. This flag decides whether the CTA is *rendered at all*. It defaults to
 *      false, matching the backend's default, so the shipped default is today's
 *      exact behaviour — a "Start Free Trial" link and no dead button.
 *   2. If it is ever true while the backend's is false, the relay turns the
 *      backend's 404 into `code: "sandbox_disabled"` and the CTA renders a
 *      plain "not available yet" line. Drift is visible and harmless, not a
 *      broken-looking error.
 *
 * Turning this on therefore takes two deliberate acts, in this order: set
 * `SANDBOX_KEYS_ENABLED=true` on invoice-be, then
 * `NEXT_PUBLIC_SANDBOX_KEYS_ENABLED=true` here. Note this is a `NEXT_PUBLIC_*`
 * value, so it is baked into the browser bundle at `docker build` time (see
 * tracker Gap 6) — flipping it needs a rebuild, not just a restart.
 */
export const SANDBOX_KEYS_ENABLED =
  process.env.NEXT_PUBLIC_SANDBOX_KEYS_ENABLED === "true";
