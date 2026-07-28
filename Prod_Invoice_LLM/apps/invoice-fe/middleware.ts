import { clerkMiddleware } from '@clerk/nextjs/server';

// Bare clerkMiddleware() -- makes Clerk's auth() context available to routes
// (needed for useUser()/useClerk() in Header.tsx) without enforcing route
// protection. No .protect() calls here, so this does not block or redirect
// any existing page; that's a separate decision for whoever builds the real
// auth gate.
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    '/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)).*)',
    // Always run on API routes (needed for auth() to work there)
    '/api/(.*)',
    '/trpc/(.*)',
  ],
};
