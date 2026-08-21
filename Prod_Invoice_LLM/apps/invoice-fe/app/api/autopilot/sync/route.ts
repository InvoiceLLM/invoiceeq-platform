import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/autopilot/sync → BE POST /autopilot/sync  ("Sync Now")
 *
 * FE Gap 278 -- see app/api/autopilot/config/route.ts for why all three
 * Autopilot proxy routes were missing.
 *
 * Worth noting what this route makes visible rather than fixes: BE Gap 288
 * (the 'gdrive' vs 'google_drive' provider mismatch in
 * services/autopilot_sync.py) was completely hidden behind the 404 here. Once
 * requests actually reach the backend, a Drive sync surfaces its real error --
 * "No active ... connection for tenant" -- instead of this route's generic
 * fallback text.
 */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/autopilot/sync");
}
