import { NextRequest, NextResponse } from "next/server";

/**
 * Public pass-through for PayU's surl/furl callbacks.
 *
 * Why this exists: `invoice-be`'s Container App ingress is `external: false`,
 * so PayU -- a third party on the public internet -- can never POST to the
 * backend's own `/api/v1/billing/payu/*` endpoints. `invoice-website` is the
 * only public origin, so `routers/billing.py` builds surl/furl from
 * `BACKEND_PUBLIC_URL` pointing here, and this forwards them inward. The
 * route path deliberately mirrors the backend's exactly so the backend needs
 * no URL-shape special-casing.
 *
 * Deliberately UNAUTHENTICATED -- unlike the sibling
 * `/api/billing/create-checkout-session` proxy, which gates on Clerk `auth()`.
 * PayU is not a signed-in user and carries no session; an `auth()` gate here
 * would break the callback outright. Security is not weakened by this:
 * `_handle_payu_callback` verifies PayU's response hash *and* does an
 * independent server-to-server `verify_payment` cross-check before trusting
 * anything, so a spoofed POST to this URL gets bounced to /billing/failed.
 *
 * `redirect: "manual"` is load-bearing. The backend answers with a 303 whose
 * Location is the user's landing page; letting fetch follow it server-side
 * would return that page's HTML body with a 200 instead of a real browser
 * redirect. That exact mistake was made and fixed once already in this repo
 * on the connectors OAuth callback (see `fe_features_tracker.md` Gap 98's
 * follow-up / `invoice-fe/app/api/connectors/callback/[provider]/route.ts`).
 */

const REDIRECT_STATUSES = [301, 302, 303, 307, 308];

/**
 * Best-effort txnid lookup, for display only, used when we cannot reach the
 * backend at all and have to build our own failure redirect. Never used to
 * make a trust decision -- that only ever happens backend-side.
 */
function txnidFromBody(body: string): string | null {
  try {
    return new URLSearchParams(body).get("txnid");
  } catch {
    return null;
  }
}

function unverifiableRedirect(request: NextRequest, body: string) {
  const txnid = txnidFromBody(body);
  const target = new URL("/billing/failed", request.nextUrl.origin);
  target.searchParams.set("reason", "unverifiable");
  if (txnid) target.searchParams.set("txnid", txnid);
  // 303 so the browser turns PayU's POST into a GET on the landing page.
  return NextResponse.redirect(target, 303);
}

export async function relayPayuCallback(
  request: NextRequest,
  outcome: "success" | "failure"
) {
  // Read the raw body first: it is needed verbatim for the forward, and as a
  // txnid source if the forward itself fails.
  const body = await request.text();

  const backendApiUrl = process.env.BACKEND_API_URL;
  if (!backendApiUrl) {
    // Do not throw: a 500 here strands a user who may have just paid. Send
    // them to the honest "we could not verify this" page instead.
    console.error("BACKEND_API_URL is not set — cannot relay PayU callback.");
    return unverifiableRedirect(request, body);
  }

  let response: Response;
  try {
    response = await fetch(
      `${backendApiUrl.replace(/\/$/, "")}/api/v1/billing/payu/${outcome}`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            request.headers.get("content-type") ||
            "application/x-www-form-urlencoded",
        },
        body,
        redirect: "manual",
        cache: "no-store",
      }
    );
  } catch (e) {
    console.error("PayU callback relay to backend failed:", e);
    return unverifiableRedirect(request, body);
  }

  const location = response.headers.get("location");
  if (location && REDIRECT_STATUSES.includes(response.status)) {
    // Resolve against this origin in case the backend ever emits a relative
    // Location; NextResponse.redirect requires an absolute URL.
    const target = new URL(location, request.nextUrl.origin);
    return NextResponse.redirect(target, response.status as 301 | 302 | 303 | 307 | 308);
  }

  // No redirect came back (unexpected — every backend path returns a 303).
  // Relay the body as-is rather than inventing a result.
  const data = await response.text();
  return new NextResponse(data, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "text/plain",
    },
  });
}
