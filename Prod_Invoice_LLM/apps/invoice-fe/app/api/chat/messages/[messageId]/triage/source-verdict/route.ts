import { type NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/**
 * POST /api/chat/messages/{messageId}/triage/source-verdict -> backend equivalent.
 *
 * Step 3, reached only when the auto-diff found chat and the DB agree: the
 * human's answer to "does the source document agree with what we stored?".
 * Body `{invoice_id, field, pdf_agrees}`.
 *
 * When `pdf_agrees` is false the response is **not** a chat correction — it
 * carries `next: "extraction_flag_missed"` plus a `redirect` block so the UI can
 * open the Trainer's extraction flow pre-filled with that invoice and field.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: { messageId: string } }
) {
  return proxyJson(request, `/chat/messages/${params.messageId}/triage/source-verdict`);
}
