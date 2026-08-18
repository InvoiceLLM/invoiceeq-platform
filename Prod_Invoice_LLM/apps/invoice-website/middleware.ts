import { clerkMiddleware } from '@clerk/nextjs/server';

// Bare clerkMiddleware() -- makes Clerk's auth() context available to routes
// (needed for useSignIn()/useSignUp()/useClerk()/useUser() in /login and
// /signup) without enforcing route protection. No .protect() calls here, so
// the marketing homepage stays fully public.
export default clerkMiddleware();

// Bug fix (2026-08-04): the matcher used to run on every /api/* path
// (including a separate, now-removed blanket '/api/(.*)' entry below, which
// would have silently re-included everything this exclusion list removes).
// For a path meant to be proxied straight through to invoice-fe (see
// next.config.js's feApiPrefixes), Clerk's own middleware was intercepting
// the request first -- for a caller with no dev-browser-sync cookie yet, it
// redirects internally to its own '/clerk_<nonce>' handshake path before our
// rewrite rule ever runs, so the request never reaches invoice-fe (or the
// backend behind it) at all. Confirmed live: DB user/tenant rowcount stayed
// 0 through multiple real login attempts, meaning `/api/auth/me` never once
// completed successfully end-to-end.
//
// Excluded below: every invoice-fe-owned prefix from next.config.js's
// feApiPrefixes, EXCEPT "auth" is narrowed to the literal "api/auth/me" --
// invoice-website has its own real route at app/api/auth/provision/route.ts,
// and a blanket "api/auth" exclusion would also pull Clerk's middleware off
// that route, an unrelated behavior change this fix has no business making.
//
// 2026-08-05: "api/webhooks" added -- it was missing from BOTH this list and
// next.config.js's feApiPrefixes (invoice-fe's app/api/webhooks/ landed after
// the original 2026-08-04 sweep), so /settings/webhooks' `GET /api/webhooks`
// hit exactly the failure mode described above: Clerk intercepted it first and
// the caller got a generic 404 with `x-middleware-rewrite: /api/webhooks`
// instead of invoice-fe's real response. Safe to exclude wholesale (unlike
// "auth") -- invoice-website has no app/api/webhooks/ route of its own.
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)|api/admin|api/audit|api/auth/me|api/billing/usage|api/chat|api/connectors|api/dashboard|api/docs|api/email|api/invoices|api/outbound-audit|api/outbound-dashboard|api/outbound-invoices|api/settings|api/support|api/trainer|api/webhooks).*)',
    '/trpc/(.*)',
  ],
};
