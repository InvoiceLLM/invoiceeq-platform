import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/chat/messages/{messageId}/triage -> backend equivalent.
 *
 * Step 2 of the wrong-data triage. Body `{invoice_id, field, claimed_value?}`.
 * The backend diffs what the reply claimed against the stored column and returns
 * `{diff, next}` — no human judgement is asked for here, because it is a value
 * comparison, and "was the number right?" is exactly the question the user came
 * here unable to answer.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: { messageId: string } }
) {
  return proxyJson(request, `/chat/messages/${params.messageId}/triage`);
}
