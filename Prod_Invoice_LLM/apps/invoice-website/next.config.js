/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    ENABLE_FE_PROXY: process.env.ENABLE_FE_PROXY || "false",
  },
  async rewrites() {
    if (process.env.ENABLE_FE_PROXY !== "true") return [];

    const feUrl = process.env.FE_INTERNAL_URL;
    if (!feUrl) throw new Error("FE_INTERNAL_URL is not set but ENABLE_FE_PROXY=true");

    const fePages = ["dashboard", "chat", "ingestion", "invoices", "trainer", "settings", "admin", "flows", "help"];
    // Bug fix (2026-08-04): "auth" was missing from this list even though
    // invoice-fe has its own app/api/auth/ route directory. useAuth.ts's
    // fetchAuth() calls a relative `GET /api/auth/me`, which resolves against
    // whatever domain the browser is actually on -- invoice-website's domain
    // for any page served through the FE-proxy. Without "auth" here, that
    // request 404'd on invoice-website's own domain (never reached FE), so
    // `loading` in useAuth() never became false, and Sidebar.tsx's
    // `loading ? <3 universal items> : item.visible` logic stayed stuck
    // showing only Dashboard/Chat/Help forever -- looked identical to "the
    // other nav items don't exist" but was actually "the permissions fetch
    // never completes". Confirmed this was the ONLY gap by diffing this array
    // against every top-level folder in apps/invoice-fe/app/api/ (13 folders:
    // admin, audit, auth, chat, connectors, dashboard, email, invoices,
    // outbound-audit, outbound-dashboard, outbound-invoices, settings,
    // trainer -- all 12 others were already present here).
    //
    // Bug fix (2026-08-05): "webhooks" was the same class of miss. invoice-fe
    // gained app/api/webhooks/route.ts + app/api/webhooks/[id]/route.ts (FE Gap
    // 107) AFTER the audit above was done, so this array was never re-diffed
    // against app/api/. /settings/webhooks calls a relative `GET /api/webhooks`,
    // which on the public invoice-website origin had no rewrite rule and no
    // middleware exclusion -- Clerk's middleware took it first and rewrote it to
    // its own handshake path (confirmed live: `x-middleware-rewrite:
    // /api/webhooks` on a 404 response), so the request never reached
    // invoice-fe. invoice-website has no app/api/webhooks/ of its own, so this
    // prefix cannot shadow a real local route. Re-diffed against
    // apps/invoice-fe/app/api/ on 2026-08-05: 14 folders, all 14 now listed.
    const feApiPrefixes = ["admin", "audit", "auth", "chat", "connectors", "dashboard", "docs", "email", "invoices", "outbound-audit", "outbound-dashboard", "outbound-invoices", "settings", "trainer", "webhooks"];

    const pageRewrites = [
      ...fePages.flatMap((p) => [
        { source: `/${p}`, destination: `${feUrl}/${p}` },
        { source: `/${p}/:path*`, destination: `${feUrl}/${p}/:path*` },
      ]),
      ...feApiPrefixes.map((p) => ({
        source: `/api/${p}/:path*`,
        destination: `${feUrl}/api/${p}/:path*`,
      })),
      // Bug fix (2026-08-03): assetPrefix="/fe-static" in invoice-fe/next.config.js
      // PREPENDS to Next's normal internal asset path -- it does not replace
      // "_next" with "fe-static". So the real emitted asset URLs are
      // "/fe-static/_next/static/...", not "/fe-static/static/...". The old rule
      // here (`source: "/fe-static/:path*"`, `destination: ${feUrl}/_next/:path*`)
      // captured the "_next/static/..." suffix in :path* and then prepended
      // ANOTHER "/_next/" onto it, producing a doubled "${feUrl}/_next/_next/
      // static/..." destination that always 404'd on FE -- confirmed via a real
      // logged-in /dashboard load rendering unstyled (zero CSS/JS loaded) and via
      // curl showing the actual referenced src="/fe-static/_next/static/..." URLs
      // 404ing. Fix: match the literal "_next/" segment in the source pattern so
      // :path* only captures what comes after it, and don't re-add "/_next/" in
      // the destination.
      { source: "/fe-static/_next/:path*", destination: `${feUrl}/_next/:path*` },
    ];

    // Bug fix (2026-08-04): even with assetPrefix="/fe-static" correctly baked
    // into invoice-fe's build (confirmed via required-server-files.json), Next.js
    // App Router does NOT apply assetPrefix uniformly to every emitted asset
    // reference in a page's initial SSR HTML. Per-page/layout chunks (the
    // page's own JS, the numbered shared vendor chunks like "138"/"73"/"957",
    // and page-level CSS) DO get the "/fe-static" prefix -- confirmed via
    // app-build-manifest.json + live HTML. But the App Router's root bootstrap
    // set -- rootMainFiles in build-manifest.json (webpack runtime, the "23"/
    // "fd9d1056" framework chunks, main-app) plus polyfillFiles and the ROOT
    // layout's own CSS -- get emitted as bare "/_next/static/..." with no
    // prefix at all (confirmed: the client hydration payload embeds
    // `"assetPrefix":""` for this specific rendering path, even though the same
    // build's required-server-files.json has "/fe-static"). Without the webpack
    // runtime, React never initializes client-side -- the page looks fine
    // (server-rendered HTML + data) but is fully non-interactive (no buttons
    // work). This looks like a genuine Next.js limitation/bug in how it
    // resolves assetPrefix for the App Router's root-level bootstrap scripts,
    // not something fixable in invoice-fe's own config.
    //
    // Fix: a catch-all fallback proxy for any bare "/_next/static/*" request
    // that invoice-website doesn't already have a real local file for. Using
    // `afterFiles` (not a plain array, which Next checks before the
    // filesystem) is essential here -- it guarantees invoice-website's OWN
    // real static chunks (its own webpack runtime, its own homepage/login/
    // signup pages' JS/CSS, all under this same generic "/_next/static/..."
    // path structure) are matched and served FIRST, and this rule only ever
    // fires as a fallback for a hash invoice-website genuinely doesn't have
    // locally (i.e., one of invoice-fe's chunks) -- it cannot ever shadow or
    // break invoice-website's own marketing-site assets.
    const fallbackStaticRewrite = [
      { source: "/_next/static/:path*", destination: `${feUrl}/_next/static/:path*` },
    ];

    return {
      afterFiles: [...pageRewrites, ...fallbackStaticRewrite],
    };
  },
};

module.exports = nextConfig;
