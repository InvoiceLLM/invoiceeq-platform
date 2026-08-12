import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

interface RouteParams {
  params: {
    id: string;
  };
}

// Gap 194: recent delivery attempts for one subscription. `proxyJson` forwards
// the query string, so `?limit=` reaches the backend unchanged.
export async function GET(request: NextRequest, { params }: RouteParams) {
  return proxyJson(request, `/webhooks/${params.id}/deliveries`);
}
