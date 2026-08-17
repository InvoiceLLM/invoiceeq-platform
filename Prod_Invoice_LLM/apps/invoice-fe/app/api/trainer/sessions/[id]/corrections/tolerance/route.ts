import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/trainer/sessions/{id}/corrections/tolerance -> backend equivalent.
 *
 * Correction #1: "this alert was unnecessary" on one of the three
 * tolerance-taking checks (`line_item_calculation_mismatch`,
 * `line_items_mismatch`, `tax_mismatch`). Body `{alert_type, field?, abs_tol,
 * rel_tol}`. Stages a candidate rule only — nothing is persisted until
 * `/preview` then `/commit`.
 *
 * The backend 400s (with a structured `rejection_reason`) for any other type,
 * including the five `*_not_verified_in_source` ones, which have no numeric band
 * to widen. That error body is forwarded verbatim so the UI can show the
 * registry's own explanation.
 */
export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  return proxyJson(request, `/trainer/sessions/${params.id}/corrections/tolerance`);
}
