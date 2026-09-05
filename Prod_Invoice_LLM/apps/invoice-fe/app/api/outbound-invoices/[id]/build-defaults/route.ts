import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 20 / BE Feature 17: prefill for the Invoice Builder.
 *
 * `proxyJson` forwards the backend status untouched, which this screen depends
 * on — 404 (not this tenant's / not outbound) and 409 (source not in
 * VERIFIED/SENT/PAID/OVERDUE, founder decision D4) both have to reach the page
 * so it can redirect with the right message instead of rendering an empty form.
 */
export async function GET(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/outbound-invoices/${params.id}/build-defaults`);
}
