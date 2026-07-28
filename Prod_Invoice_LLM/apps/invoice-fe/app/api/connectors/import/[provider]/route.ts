import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/connectors/import/[provider] → BE POST /connectors/import/{provider} */
export async function POST(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  return proxyJson(request, `/connectors/import/${params.provider}`);
}
