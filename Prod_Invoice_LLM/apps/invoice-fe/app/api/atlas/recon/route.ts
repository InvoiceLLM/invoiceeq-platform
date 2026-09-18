// =============================================================================
// FILE: app/api/atlas/recon/route.ts
// FEATURE: FE Feature 23 §6 — attach a vendor statement, get the four groups.
//
// POST, not GET, because the backend reads a document and compares it against
// the whole ledger; it is a computation with a body, not an addressable
// resource. It still writes nothing (BE §15.5).
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/atlas/recon → BE POST /api/v1/atlas/recon */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/atlas/recon");
}
