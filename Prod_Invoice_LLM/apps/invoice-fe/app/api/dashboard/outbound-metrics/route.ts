import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * Feature 2.1, Task 2.1.3 — Outbound Dashboard metrics proxy.
 * FE path : /api/dashboard/outbound-metrics
 * BE path : /api/v1/outbound-dashboard/metrics
 *
 * Separate route from /api/dashboard/metrics rather than a direction param on
 * it, matching the BE's own zero-touch split (routers/outbound_dashboard.py).
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/outbound-dashboard/metrics");
}
