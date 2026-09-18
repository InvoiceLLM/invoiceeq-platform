// =============================================================================
// FILE: app/api/atlas/missed/route.ts
// FEATURE: FE Feature 23 — BE Feature 34 task 34.14 (§5.2 Q13, D34).
//
// invoice-be's ingress is `external: false`; every call goes through a route
// handler. Same `proxyJson` + `force-dynamic` shape as the rest of this feature.
//
// THE USER'S SENTENCE PASSES THROUGH UNTOUCHED. It is the evidence that ATLAS
// was wrong, and it becomes a memory rule the whole workspace can read
// (BE §7.2). Trimming, summarising or "cleaning" it anywhere along this path
// would be the product editing its own report card.
//
// NOT CAPABILITY-GATED HERE OR THERE. A miss is noticed by whoever happens to be
// looking; §5.2 says false negatives are already invisible and under-reported,
// and a gate would suppress exactly the evidence that is scarcest.
// =============================================================================
import { NextRequest } from "next/server";

import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** POST /api/atlas/missed → BE POST /api/v1/atlas/missed */
export async function POST(request: NextRequest) {
  return proxyJson(request, "/atlas/missed");
}
