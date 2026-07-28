import { clerkMiddleware } from '@clerk/nextjs/server';

// Bare clerkMiddleware() -- makes Clerk's auth() context available to routes
// (needed for useSignIn()/useSignUp()/useClerk()/useUser() in /login and
// /signup) without enforcing route protection. No .protect() calls here, so
// the marketing homepage stays fully public.
export default clerkMiddleware();

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)).*)',
    '/api/(.*)',
    '/trpc/(.*)',
  ],
};
