import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

// GET /api/trainer/vendors -> backend /trainer/vendors
// Vendor list (with a sample invoice each) for the Existing-Vendor scope picker.
export async function GET(request: NextRequest) {
  return proxyJson(request, "/trainer/vendors");
}
