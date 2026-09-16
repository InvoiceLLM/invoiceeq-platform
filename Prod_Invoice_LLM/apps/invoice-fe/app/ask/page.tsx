"use client";

// =============================================================================
// FILE: app/ask/page.tsx
// FEATURE: FE Feature 22 Task 22.6 — Ask: "let me ask, or do, something".
//
// The chat screen (components/chat/ChatScreen.tsx) under its new name, plus the
// deep links Today sends (task 22.5):
//   /ask?session=<id>&seed=<question>   a finding or summary line, opened
//   /ask?attach=1                        an input request asking for a document
//   /ask?invoice=<id>                    the old review URL (22.12) — ReviewCard
// =============================================================================

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import ChatScreen, { type ChatDeepLink } from "@/components/chat/ChatScreen";

function AskContent() {
  const params = useSearchParams();
  const sessionId = params.get("session");
  const seed = params.get("seed");
  const attach = params.get("attach") === "1";
  const invoiceId = params.get("invoice");

  const deepLink = useMemo<ChatDeepLink | undefined>(
    () => (sessionId || seed || attach || invoiceId ? { sessionId, seed, attach, invoiceId } : undefined),
    [sessionId, seed, attach, invoiceId]
  );

  return <ChatScreen title="Ask" deepLink={deepLink} />;
}

export default function AskPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-white">Loading Ask…</div>}>
      <AskContent />
    </Suspense>
  );
}
