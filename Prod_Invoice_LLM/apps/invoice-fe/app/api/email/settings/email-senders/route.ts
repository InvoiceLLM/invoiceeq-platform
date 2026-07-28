import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/email/settings/email-senders → BE GET /email/settings/email-senders */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/email/settings/email-senders");
}

/** POST /api/email/settings/email-senders → BE POST /email/settings/email-senders */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/email/settings/email-senders");
}
