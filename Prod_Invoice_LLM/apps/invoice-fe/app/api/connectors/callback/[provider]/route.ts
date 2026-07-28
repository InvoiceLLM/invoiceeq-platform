import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/connectors/callback/[provider] → BE GET /connectors/callback/{provider} */
export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  return proxyJson(request, `/connectors/callback/${params.provider}`);
}
