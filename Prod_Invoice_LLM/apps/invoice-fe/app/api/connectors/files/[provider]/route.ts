import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** GET /api/connectors/files/[provider] → BE GET /connectors/files/{provider} */
export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  return proxyJson(request, `/connectors/files/${params.provider}`);
}
