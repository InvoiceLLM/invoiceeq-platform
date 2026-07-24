import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// POST /api/trainer/sessions/{id}/commit -> backend equivalent. No body needed;
// the scope is derived from the stored session server-side.
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/commit`);
}
