import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 20 / BE Feature 17: creates the cloned invoice and enqueues it into
 * the same outbound pipeline an upload uses. Returns `{batch_id, invoice_id}`.
 *
 * 409 (invoice number already used for this customer, founder decision D5) and
 * 422 (a changed field could not be located in the source PDF) are forwarded
 * unchanged for the builder page to render inline.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/outbound-invoices/build");
}
