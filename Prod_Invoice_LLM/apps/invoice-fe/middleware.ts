import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

// FE Gap 358: every /api/* route is exempted from .protect() below, not just
// '/flows'. invoice-be re-authenticates every request itself regardless
// (Depends(get_tenant_context) / get_tenant_or_api_key_context / require_admin
// on all 20 routers, no unauthenticated fallback) -- Clerk's .protect() here
// was never the real authorization boundary, it only asserted "a session
// exists" with no role/MFA/org-switch check of its own. Its one live effect
// on /api/* was forcing a dev-browser handshake redirect on every request
// with no Clerk cookie, which 404s any external caller (including a real
// inv_live_ API key) before it ever reaches invoice-be. Verified before this
// change: all BE routes with no tenant-auth dependency (PayU callbacks,
// logout, the mail-integration webhook, sandbox key issue, widget/docs
// stubs) are deliberately public AND none of them are proxied by invoice-fe,
// so exempting /api/* here does not expose anything that was actually
// protected.
const isPublicRoute = createRouteMatcher([
  '/flows(.*)',
  '/api/(.*)',
]);

export default clerkMiddleware((auth, req) => {
  // Allow bypassing auth gating in local Playwright test environments
  if (process.env.DISABLE_CLERK_AUTH === 'true') {
    return;
  }

  if (!isPublicRoute(req)) {
    const { userId } = auth();
    if (!userId) {
      const host = req.headers.get('host') || 'invoicellm.admsofttech.com';
      const protocol = req.headers.get('x-forwarded-proto') || 'https';
      const origin = `${protocol}://${host}`;

      const signInUrl = new URL('/login', origin);
      signInUrl.searchParams.set('redirect_url', req.nextUrl.pathname);
      return NextResponse.redirect(signInUrl);
    }
    auth().protect();
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    '/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)).*)',
    // Always run on API routes (needed for auth() to work there)
    '/api/(.*)',
    '/trpc/(.*)',
  ],
};
