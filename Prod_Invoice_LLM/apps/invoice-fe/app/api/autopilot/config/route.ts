import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * GET  /api/autopilot/config → BE GET  /autopilot/config
 * PUT  /api/autopilot/config → BE PUT  /autopilot/config
 *
 * FE Gap 278: Feature 13 (Autopilot) shipped its UI and its backend router but
 * never its proxy routes. `lib/apiClient.ts` is same-origin only
 * (`baseURL: "/api"`), and invoice-fe's next.config.js defines no `rewrites()`
 * -- only `assetPrefix` -- so there is no fallback path to the backend. Every
 * Autopilot call therefore 404'd at Next.js itself and never reached FastAPI.
 *
 * The failure was near-silent by design accident: app/ingestion/page.tsx
 * swallows a failed config load with `catch { // No config yet -- defaults are
 * fine }`, so the tab rendered normally with default values while Save, Sync
 * and History all failed. And because a Next 404 returns an HTML page rather
 * than JSON, `err.response.data.detail` was always undefined and every call
 * site fell back to its generic message ("Sync failed. Please check your
 * configuration."), masking the fact that the backend was never consulted.
 */
export async function GET(request: NextRequest) {
  return proxyJson(request, "/autopilot/config");
}

export async function PUT(request: NextRequest) {
  return proxyJson(request, "/autopilot/config");
}
