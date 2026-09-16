// =============================================================================
// FILE: lib/navigation.ts
// FEATURE: FE Feature 22 Task 22.1 — the four-surface navigation's pure half:
//          the rollout switch, the old-route -> new-home map, and the one
//          active-link rule both navs share.
//
// WHY A ROLLOUT SWITCH (not in the spec, added deliberately — flagged in the
// plan's ledger). Task 22.1 lands before the surfaces it points at: `/records`
// is 22.2, `/today` is 22.4, `/ask` is 22.6. Mounting PrimaryNav and these
// redirects unconditionally would send `/chat` and `/invoices` — the chat and
// the audit queue — to 404s for every user until Slice F4. So the whole thing
// sits behind `NEXT_PUBLIC_FOUR_SURFACES`, default OFF: off is byte-for-byte
// today's shell. Task 22.21's per-user `layout` preference later decides
// surfaces-vs-classic PER USER; this switch decides whether the four surfaces
// are offered AT ALL. Inlined at build time, like every NEXT_PUBLIC_* var.
//
// WHY THE MAP IS SHORT. Level L2 (spec §1) keeps review as a page, so
// `/invoices/review/[id]` did NOT redirect until L3 (22.12, now `/ask?invoice=`);
// `/invoices/outbound-review/[id]` still does not. `/trainer` and `/help` are L3 too (22.13, 22.15) — each task
// adds its own row here, so the ledger and this table stay in step. `/ingestion` stays by ruling (22.24);
// `/settings/chat-rules` keeps its own page (FE Gap 478).
// =============================================================================

/** Whether the four surfaces (PrimaryNav + old-route redirects) are switched on. */
export function fourSurfacesEnabled(): boolean {
  return process.env.NEXT_PUBLIC_FOUR_SURFACES === "true";
}

export interface LegacyRedirect {
  /**
   * Matched EXACTLY, segment for segment — `/invoices` must not swallow
   * `/invoices/review/[id]`. A `:name` segment matches one non-empty segment
   * and is substituted (URL-encoded) wherever `:name` appears in `to`.
   */
  from: string;
  to: string;
  /** The Feature 22 task that owns this row. */
  task: string;
}

export const LEGACY_ROUTE_REDIRECTS: readonly LegacyRedirect[] = [
  { from: "/chat", to: "/ask", task: "22.1" },
  { from: "/invoices", to: "/records?tab=in", task: "22.1" },
  // FE Gap 464 made /history the one screen for every uploaded file — failed
  // uploads, rejected emails, connector imports — i.e. the ingestion log, which
  // spec §1 moves to Records. `documents` is the nearest of Records' four tabs;
  // founder to confirm (plan §6 open items).
  { from: "/history", to: "/records?tab=documents", task: "22.1" },
  // The builder is a drawer over Invoices out now; `?source=` is carried over
  // by legacyRedirectFor and is exactly the parameter that opens the drawer.
  { from: "/invoices/outbound-builder", to: "/records?tab=out", task: "22.2" },
  // Settings is one scrolling page; each sub-route lands on its section
  // (components/settings/SettingsSections.tsx). NOT here, deliberately:
  // `/settings/chat-rules` keeps its own page (FE Gap 478), and
  // `/settings/connectors` is the backend's Google OAuth return URL, rendered
  // inside the consent popup (invoice-be routers/connectors.py:249).
  { from: "/admin", to: "/settings#people", task: "22.3" },
  { from: "/settings/email", to: "/settings#inbox", task: "22.3" },
  { from: "/settings/workflows", to: "/settings#checks", task: "22.3" },
  { from: "/settings/webhooks", to: "/settings#notify", task: "22.3" },
  { from: "/settings/subscriptions", to: "/settings#plan", task: "22.3" },
  { from: "/settings/security", to: "/settings#security", task: "22.3" },
  // The dashboard's data is Today's now (22.9). TODO(22.21): under the classic
  // layout /dashboard must RENDER, not redirect -- 22.21 decides this per user.
  { from: "/dashboard", to: "/today", task: "22.9" },
  // Review is a card in Ask at L3 (22.12). `:id` matches exactly ONE path
  // segment. `/invoices/outbound-review/[id]` stays a page — the card links there.
  { from: "/invoices/review/:id", to: "/ask?invoice=:id", task: "22.12" },
  // The Trainer is a mode of Ask (22.13): `teach: …` in the composer. Exact
  // match only; the page's other tools stay reachable under the classic layout
  // (plan open item #27).
  { from: "/trainer", to: "/ask", task: "22.13" },
];

/** Path params when `pathname` matches `pattern` segment for segment, else null. */
function matchRoute(pattern: string, pathname: string): Record<string, string> | null {
  const want = pattern.split("/");
  const got = pathname.split("/");
  if (want.length !== got.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i += 1) {
    if (want[i].startsWith(":")) {
      if (!got[i]) return null;
      params[want[i].slice(1)] = got[i];
    } else if (want[i] !== got[i]) {
      return null;
    }
  }
  return params;
}

/**
 * Where an old route now lives, or `null` when it stays put. The incoming query
 * string is carried over (`/chat?session=…` -> `/ask?session=…`), but the
 * target's own keys win — an old `?tab=` must not pick a different Records tab.
 */
export function legacyRedirectFor(pathname: string, search = ""): string | null {
  let params: Record<string, string> | null = null;
  const row = LEGACY_ROUTE_REDIRECTS.find((r) => (params = matchRoute(r.from, pathname)) !== null);
  if (!row || !params) return null;
  const to = row.to.replace(/:([a-z]+)/gi, (_, name: string) => encodeURIComponent((params as Record<string, string>)[name] ?? ""));

  // A `#section` target keeps its hash LAST — `/settings?x=1#inbox`, never
  // `/settings#inbox?x=1`, where the query would silently become part of the hash.
  const [target, hash = ""] = to.split("#");
  const [path, targetQuery = ""] = target.split("?");
  const merged = new URLSearchParams(targetQuery);
  new URLSearchParams(search).forEach((value, key) => {
    if (!merged.has(key)) merged.append(key, value);
  });
  const query = merged.toString();
  return `${path}${query ? `?${query}` : ""}${hash ? `#${hash}` : ""}`;
}

/**
 * FE Gap 143's rule, shared rather than re-derived: the most specific matching
 * item wins, so `/settings` and `/settings/subscriptions` never light up
 * together. Extracted verbatim from `Sidebar.tsx` so PrimaryNav cannot drift
 * from it.
 */
export function activeNavHref(items: readonly { href: string }[], pathname: string): string | undefined {
  return items
    .filter((item) => pathname === item.href || pathname.startsWith(item.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
}
