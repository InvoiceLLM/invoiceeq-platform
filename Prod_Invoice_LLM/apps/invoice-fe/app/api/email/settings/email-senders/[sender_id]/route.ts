import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** DELETE /api/email/settings/email-senders/[sender_id] → BE DELETE /email/settings/email-senders/{sender_id} */
export async function DELETE(
  request: NextRequest,
  { params }: { params: { sender_id: string } }
) {
  return proxyJson(request, `/email/settings/email-senders/${params.sender_id}`);
}
