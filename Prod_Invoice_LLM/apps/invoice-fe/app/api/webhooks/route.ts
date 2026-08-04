import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export async function GET(request: NextRequest) {
  return proxyJson(request, "/webhooks");
}

export async function POST(request: NextRequest) {
  return proxyJson(request, "/webhooks");
}
