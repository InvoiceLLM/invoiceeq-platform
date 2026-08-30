import { NextRequest, NextResponse } from "next/server";
import { auth } from "@clerk/nextjs/server";

export const dynamic = "force-dynamic";

/**
 * Website Gap 350 — sandbox claim relay.
 *
 * Website path : POST /api/sandbox/claim
 * Backend path : POST /api/v1/sandbox/claim   (BE Feature 25 / Gap 340)
 *
 * Promotes the sandbox workspace a visitor was issued (`inv_test_...`) into the
 * real workspace they have just signed up for, so their trial invoices, chat
 * sessions and workflow config survive signup instead of being abandoned in a
 * tenant nobody will ever look at again.
 *
 * AUTHENTICATED, and by the same mechanism as `/api/auth/provision` — this is a
 * near-copy of that handler on purpose, because the backend endpoint takes the
 * *same* Clerk dependency and applies the *same* two bindings (Gap 133
 * Checkpoint 3c): the body's `clerk_user_id` must equal the token's `sub`, and
 * the body's `clerk_org_id` must equal the token's active `org_id`. Without a
 * real token the backend rejects the claim, which is the point — otherwise any
 * caller holding a scraped sandbox key could claim it into somebody else's
 * organisation.
 *
 * The token is preferred from the caller's own `Authorization` header: the
 * signup page mints it client-side immediately after `setActive`, and the
 * session cookie `auth()` reads can lag a just-completed `setActive` (Gap 157
 * proved this live). The cookie path is the fallback, not the primary.
 *
 * FAILURE IS NOT FATAL, BY DESIGN. The caller (app/signup/page.tsx) treats
 * every non-2xx here as "no claim happened" and continues with an ordinary
 * fresh signup. Claiming is an upgrade path, not a dependency of signing up, so
 * nothing in this handler blocks — it reports and gets out of the way. The
 * backend's own outcomes are already shaped for that: 409 already-claimed /
 * not-claimable, 410 expired, 404 when `SANDBOX_KEYS_ENABLED` is off.
 */
export async function POST(request: NextRequest) {
  const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";

  const body = await request.text();

  let token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || null;
  if (!token) {
    try {
      const { userId, getToken } = await auth();
      if (userId) {
        // The `invoice-app` template, not a bare getToken(): the bare session
        // token carries none of this app's custom claims (Gap 109 / Gap 174).
        token = await getToken({ template: "invoice-app" });
      }
    } catch (authErr) {
      console.error("[sandbox/claim] could not read Clerk session server-side:", authErr);
    }
  }

  if (!token) {
    console.error("[sandbox/claim] no Clerk session token available; refusing to call backend");
    return NextResponse.json(
      {
        detail: "Not signed in. Claiming a sandbox workspace requires a session.",
        code: "unauthenticated",
      },
      { status: 401 }
    );
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(`${backendApiUrl.replace(/\/$/, "")}/api/v1/sandbox/claim`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body,
      cache: "no-store",
    });
  } catch (err) {
    console.error("[sandbox/claim] backend unreachable:", err);
    return NextResponse.json(
      { detail: "Sandbox claim service unreachable", code: "unreachable" },
      { status: 502 }
    );
  }

  const data = (await backendRes.json().catch(() => ({}))) as { detail?: string };

  if (backendRes.status === 404) {
    // Same signal as the issuance relay: the feature flag is off. Reported with
    // an explicit code rather than a bare 404 so the signup page can tell
    // "the feature is off" apart from "the claim was refused", and log
    // accordingly. Either way signup carries on.
    console.warn(
      "[sandbox/claim] backend returned 404 — SANDBOX_KEYS_ENABLED is off in this deployment."
    );
    return NextResponse.json(
      { detail: "Sandbox claiming is not enabled.", code: "sandbox_disabled" },
      { status: 503 }
    );
  }

  if (!backendRes.ok) {
    // Logged server-side at full fidelity because the browser deliberately does
    // not surface this to the user — a failed claim is silent by design.
    console.error("[sandbox/claim] backend returned %d: %o", backendRes.status, data);
  }

  return NextResponse.json(data, { status: backendRes.status });
}
