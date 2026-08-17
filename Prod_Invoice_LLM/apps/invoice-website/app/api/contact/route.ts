import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Feature Website 5: Contact Us page API proxy.
 *
 * Website path : /api/contact
 * Backend path : /api/v1/support/contact
 *
 * This is a PUBLIC, unauthenticated endpoint — it mirrors the
 * /auth/provision pattern (also unauthenticated), forwarding the
 * browser's JSON body to the backend.
 *
 * The backend has internal-only ingress in Azure (invoice-be.bicep sets
 * ingress.external: false), so the browser can never reach it directly.
 * This server-side proxy bridges the gap, keeping the backend origin
 * out of the client bundle.
 *
 * Rate-limiting / abuse prevention is handled entirely by the backend
 * (FastAPI validation + a fixed-size random ticket number space), not
 * here — any envelope validation done here is best-effort only.
 */

const REQUIRED_FIELDS = ["name", "email", "message"] as const;

export async function POST(request: NextRequest) {
  const backendApiUrl =
    process.env.BACKEND_API_URL || "http://localhost:8000";

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Invalid JSON body" },
      { status: 400 }
    );
  }

  // Basic envelope validation — the backend validates more strictly
  for (const field of REQUIRED_FIELDS) {
    const val = (body[field] as string | undefined)?.trim();
    if (!val) {
      return NextResponse.json(
        { detail: `${field} is required` },
        { status: 422 }
      );
    }
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${backendApiUrl}/api/v1/support/contact`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
  } catch (err) {
    console.error("[contact/route] backend unreachable:", err);
    return NextResponse.json(
      { detail: "Support service temporarily unavailable. Please try again shortly." },
      { status: 503 }
    );
  }

  const data = await backendRes.json().catch(() => ({}));

  if (!backendRes.ok) {
    console.error(
      "[contact/route] backend returned %d: %o",
      backendRes.status,
      data
    );
    return NextResponse.json(
      { detail: data?.detail || "Failed to submit inquiry. Please try again." },
      { status: backendRes.status }
    );
  }

  return NextResponse.json(data, { status: backendRes.status });
}
