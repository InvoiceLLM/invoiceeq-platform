/**
 * Gap 423: one place that decides which permission a route needs.
 *
 * WHY THIS FILE EXISTS. `Sidebar.tsx` filtered nav links by permission, but
 * nothing guarded the routes themselves — `middleware.ts` calls only
 * `auth().protect()`, which asserts "a session exists" and performs no role or
 * permission check at all. So typing a URL reached any page in the app
 * regardless of permissions. QA found this by editing the address bar.
 *
 * WHAT THIS DOES AND DOES NOT FIX. Every *action* was already safe: the
 * backend gates writes with `require_can_audit` / `require_can_load` /
 * `require_admin` and returns 403 no matter how the request arrives. What was
 * wrong was the product behaviour — a user reaching a screen they were told
 * they cannot use, then watching its calls fail. This guard fixes that.
 * It is **not** a security boundary and must never be treated as one; the
 * backend remains the only enforcement.
 *
 * Note also that `GET /invoices` (list/detail/pdf) is deliberately ungated
 * backend-side so the Dashboard works for a permission-less user, which means
 * invoice *data* is still reachable by a determined caller. Changing that is a
 * product decision with real blast radius (Dashboard, widgets, chat citations)
 * and is deliberately not bundled into this UI fix.
 *
 * Single source of truth: `Sidebar.tsx` imports `canAccessRoute` from here too,
 * so a hidden link and a blocked route can never disagree.
 */

export type RoutePermission = "public" | "canLoad" | "canAudit" | "canTrain" | "admin";

export interface RoutePermissionRule {
  /** Path prefix. Longest match wins, so /settings/subscriptions can differ from /settings. */
  prefix: string;
  required: RoutePermission;
  /** Shown on the Access Restricted screen so the user knows what to ask for. */
  label: string;
}

/**
 * Ordered longest-prefix-first at match time, not here — keep this list
 * readable and let `ruleForPath` handle specificity.
 */
export const ROUTE_PERMISSIONS: RoutePermissionRule[] = [
  { prefix: "/dashboard", required: "public", label: "Dashboard" },
  { prefix: "/chat", required: "public", label: "Chat" },
  { prefix: "/help", required: "public", label: "Help Center" },
  { prefix: "/flows", required: "public", label: "Flows" },

  { prefix: "/ingestion", required: "canLoad", label: "Ingestion" },
  { prefix: "/invoices", required: "canAudit", label: "the Audit Queue" },
  { prefix: "/documents", required: "canAudit", label: "Documents" },
  { prefix: "/trainer", required: "canTrain", label: "the AI Trainer" },

  // Admin-only. `/settings/subscriptions` is Admin too, so no separate rule is
  // needed — but the longest-match logic below means adding one later works.
  { prefix: "/settings", required: "admin", label: "Settings" },
  { prefix: "/admin", required: "admin", label: "the Admin console" },
];

/** The most specific rule for a path, or null when the route is unlisted. */
export function ruleForPath(pathname: string): RoutePermissionRule | null {
  let best: RoutePermissionRule | null = null;
  for (const rule of ROUTE_PERMISSIONS) {
    if (pathname === rule.prefix || pathname.startsWith(rule.prefix + "/")) {
      if (!best || rule.prefix.length > best.prefix.length) best = rule;
    }
  }
  return best;
}

export interface PermissionSnapshot {
  role: string;
  canLoad: boolean;
  canAudit: boolean;
  canTrain: boolean;
}

/**
 * Whether this identity may open this route.
 *
 * An **unlisted** route returns true deliberately: this map must not become a
 * blocklist that silently hides a new page someone forgot to register here.
 * Unlisted means "not permission-gated", and the backend still guards its data.
 */
export function canAccessRoute(pathname: string, perms: PermissionSnapshot): boolean {
  const rule = ruleForPath(pathname);
  if (!rule) return true;
  // Admin implies every permission, resolved backend-side in
  // dependencies.resolve_permissions() — mirrored, not re-derived.
  if (perms.role === "Admin") return true;
  switch (rule.required) {
    case "public":
      return true;
    case "canLoad":
      return perms.canLoad;
    case "canAudit":
      return perms.canAudit;
    case "canTrain":
      return perms.canTrain;
    case "admin":
      return false;
    default:
      return true;
  }
}
