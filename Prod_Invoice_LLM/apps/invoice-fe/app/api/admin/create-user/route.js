import { NextResponse } from 'next/server';
import { auth } from '@clerk/nextjs/server';

/**
 * POST /api/admin/create-user
 * Creates a new Clerk user and adds them to the caller's organization as
 * "org:member", using Clerk REST API directly.
 * Using REST API directly (not SDK wrapper) to avoid SDK version compatibility issues
 * with email verification.
 *
 * Body: { firstName, lastName, email, password }
 *
 * Gap 10: this route had no auth check at all -- anyone who found the URL,
 * signed in or not, could create arbitrary Clerk accounts using this app's
 * own CLERK_SECRET_KEY. Fixed by requiring a real signed-in session AND
 * verifying Admin role via the backend's GET /auth/me (the authoritative,
 * DB-backed role resolution `dependencies.py::get_tenant_context()` already
 * does) -- not Clerk's client-editable unsafe_metadata, which a user could
 * set on themselves via the client SDK and is not a real authorization
 * boundary.
 *
 * Gap 173: users created here used to never become Clerk Organization
 * members, so they had no `org_role` at all -- the backend's role
 * resolution then had no choice but to fall back to the client-writable
 * `unsafe_metadata.role`, clamped to never reach Admin. Now every created
 * user is added to the caller's own organization (role: "org:member"), so
 * `org_role` -- changeable only via Clerk's own permission-checked
 * Organizations API, never by the user themselves -- is the single source
 * of truth for everyone, the same way it already was for the org creator.
 */
export async function POST(request) {
  try {
    const { userId, getToken } = await auth();
    if (!userId) {
      return NextResponse.json({ error: 'Not authenticated.' }, { status: 401 });
    }

    const secretKey = process.env.CLERK_SECRET_KEY;
    if (!secretKey) {
      return NextResponse.json({ error: 'CLERK_SECRET_KEY is not configured.' }, { status: 500 });
    }

    // Gap 173 follow-up: resolve the caller's organization authoritatively via
    // Clerk's Backend API rather than trusting auth()'s own `orgId`, which is
    // read from the session cookie -- a short-lived, periodically-refreshed
    // token that can lag behind Clerk.setActive({organization}) on the
    // client. Confirmed live: the browser's own window.Clerk state showed the
    // correct active org while auth()'s orgId came back empty for this exact
    // request. This call always reflects Clerk's real, current membership
    // state, independent of any session-cookie staleness.
    const membershipsRes = await fetch(
      `https://api.clerk.com/v1/users/${userId}/organization_memberships`,
      { headers: { Authorization: `Bearer ${secretKey}` } }
    );
    const membershipsData = await membershipsRes.json();
    const memberships = Array.isArray(membershipsData) ? membershipsData : membershipsData.data || [];
    const orgId = memberships[0]?.organization?.id;

    if (!orgId) {
      return NextResponse.json(
        { error: 'No organization found for this account -- cannot add the new user to it.' },
        { status: 400 }
      );
    }

    const backendApiUrl = process.env.BACKEND_API_URL;
    if (!backendApiUrl) {
      throw new Error('BACKEND_API_URL is not set');
    }

    const sessionToken = await getToken({ template: "invoice-app" });
    const meRes = await fetch(`${backendApiUrl.replace(/\/$/, '')}/auth/me`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });

    if (!meRes.ok) {
      return NextResponse.json({ error: 'Could not verify caller identity.' }, { status: 401 });
    }

    const callerContext = await meRes.json();
    if (callerContext.role !== 'Admin') {
      return NextResponse.json({ error: 'Admin role required to create users.' }, { status: 403 });
    }

    const body = await request.json();
    const { firstName, lastName, email, password } = body;

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json(
        { error: 'firstName, lastName, email, and password are required.' },
        { status: 400 }
      );
    }

    // ── Step 1: Create user via Clerk REST API ───────────────────────────
    const createRes = await fetch('https://api.clerk.com/v1/users', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secretKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        first_name: firstName,
        last_name: lastName,
        email_address: [email],
        password,
        skip_password_checks: true,
        skip_password_requirement: true,
        unsafe_metadata: { role: 'member' },
      }),
    });

    const user = await createRes.json();

    if (!createRes.ok) {
      const errMsg = user?.errors?.[0]?.long_message || user?.errors?.[0]?.message || 'Failed to create user in Clerk.';
      return NextResponse.json({ error: errMsg }, { status: 400 });
    }

    // ── Step 1b: Add to the caller's organization (Gap 173) ───────────────
    // role: "org:member", never "org:admin" -- this endpoint has never
    // granted Admin (see admin.py's set_permissions docstring) and still
    // doesn't; org:admin can only ever come from Clerk's own Organizations
    // API/Dashboard, promoting someone who is already a member.
    const membershipRes = await fetch(`https://api.clerk.com/v1/organizations/${orgId}/memberships`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secretKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ user_id: user.id, role: 'org:member' }),
    });

    if (!membershipRes.ok) {
      const membershipErr = await membershipRes.json().catch(() => ({}));
      console.warn('Adding new user to organization failed:', membershipErr);
    }

    // ── Step 2: Mark primary email as verified so sign-in works immediately ───
    const primaryEmailId = user.email_addresses?.[0]?.id;
    let emailVerified = false;

    if (primaryEmailId) {
      const verifyRes = await fetch(`https://api.clerk.com/v1/email_addresses/${primaryEmailId}`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${secretKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ verified: true }),
      });

      const verifyData = await verifyRes.json();
      emailVerified = verifyRes.ok;

      if (!verifyRes.ok) {
        console.warn('Email verification PATCH failed:', verifyData);
      }
    }

    return NextResponse.json({
      success: true,
      userId: user.id,
      email: user.email_addresses?.[0]?.email_address,
      name: `${user.first_name} ${user.last_name}`,
      emailVerified,
    });

  } catch (err) {
    console.error('create-user route error:', err);
    return NextResponse.json({ error: err?.message || 'Unexpected server error.' }, { status: 500 });
  }
}
