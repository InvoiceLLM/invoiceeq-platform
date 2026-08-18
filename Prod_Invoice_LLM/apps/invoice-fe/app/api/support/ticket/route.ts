import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * FE path : /api/support/ticket
 * BE path : /api/v1/support/ticket
 *
 * Proxies authenticated support ticket creation from the Help Center to the
 * backend support router. Automatically attaches the Clerk session token
 * (with "invoice-app" template claims).
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/support/ticket");
}

export async function GET(request: NextRequest) {
  return proxyJson(request, "/support/tickets");
}
