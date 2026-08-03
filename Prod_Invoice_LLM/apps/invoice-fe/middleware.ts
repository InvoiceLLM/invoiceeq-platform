import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

const isPublicRoute = createRouteMatcher([
  '/flows(.*)',
]);

export default clerkMiddleware((auth, req) => {
  // Allow bypassing auth gating in local Playwright test environments
  if (process.env.DISABLE_CLERK_AUTH === 'true') {
    return;
  }

  if (!isPublicRoute(req)) {
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
