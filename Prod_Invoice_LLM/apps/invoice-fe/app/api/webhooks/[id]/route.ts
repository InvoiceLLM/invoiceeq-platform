import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

interface RouteParams {
  params: {
    id: string;
  };
}

export async function PUT(request: NextRequest, { params }: RouteParams) {
  return proxyJson(request, `/webhooks/${params.id}`);
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  return proxyJson(request, `/webhooks/${params.id}`);
}
