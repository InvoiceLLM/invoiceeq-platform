import { NextResponse } from 'next/server';

/**
 * POST /api/admin/create-user
 * Creates a new Clerk user with role: 'user' using Clerk REST API directly.
 * Using REST API directly (not SDK wrapper) to avoid SDK version compatibility issues
 * with email verification.
 *
 * Body: { firstName, lastName, email, password }
 */
export async function POST(request) {
  try {
    const body = await request.json();
    const { firstName, lastName, email, password } = body;

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json(
        { error: 'firstName, lastName, email, and password are required.' },
        { status: 400 }
      );
    }

    const secretKey = process.env.CLERK_SECRET_KEY;
    if (!secretKey) {
      return NextResponse.json({ error: 'CLERK_SECRET_KEY is not configured.' }, { status: 500 });
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
        unsafe_metadata: { role: 'user' },
      }),
    });

    const user = await createRes.json();

    if (!createRes.ok) {
      const errMsg = user?.errors?.[0]?.long_message || user?.errors?.[0]?.message || 'Failed to create user in Clerk.';
      return NextResponse.json({ error: errMsg }, { status: 400 });
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
