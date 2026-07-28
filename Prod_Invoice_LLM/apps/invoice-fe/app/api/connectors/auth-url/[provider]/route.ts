import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/connectors/auth-url/[provider] → BE GET /connectors/auth-url/{provider} */
export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  return proxyJson(request, `/connectors/auth-url/${params.provider}`);
}
