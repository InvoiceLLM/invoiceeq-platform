import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyJson(request, "/dashboard/insights/dismiss");
}
