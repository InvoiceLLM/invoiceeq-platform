import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** DELETE /api/connectors/[provider] → BE DELETE /connectors/{provider} */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  return proxyJson(request, `/connectors/${params.provider}`);
}
