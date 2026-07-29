import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/outbound-dashboard/invoices");
}
