import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

/** GET /api/email/settings/mailbox → BE GET /email/settings/mailbox */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/email/settings/mailbox");
}
