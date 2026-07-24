import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// POST /api/trainer/templates/{id}/rollback/{version} -> backend equivalent.
export async function POST(
  request: NextRequest,
  { params }: { params: { id: string; version: string } }
) {
  return proxyJson(request, `/trainer/templates/${params.id}/rollback/${params.version}`);
}
