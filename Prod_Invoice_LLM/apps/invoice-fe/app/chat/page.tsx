"use client";
// WHY "use client": this page uses useChatSession which calls useState/useEffect
//   and calls apiClient (browser Axios).  Next.js requires the client directive
//   on any component that uses browser-only React hooks or browser APIs.

import { useCallback, useMemo, useState } from "react";

import { useChatSession } from "@/hooks/useChatSession";
import ChatWindow from "@/components/chat/ChatWindow";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

export default function ChatPage() {
  // FE Gap 110: Chat never had a page title of its own -- it went straight into
  // ChatWindow's own slim agent strip -- which would have left it as the one
  // screen with an unnamed header once every other route started declaring
  // one. Declaring it here costs nothing and changes no page markup.
  usePageHeader({
    title: "Semantic Chat",
    agentIcon: "🧠",
    agentName: "SAGE",
    agentRole: "Query & Insights",
  });

  // Destructure only the values that ChatWindow needs.
  // useChatSession owns all state and async actions — page.tsx is intentionally
  // thin so the same hook could power a different layout in the future without
  // rewriting any business logic.
  const {
    sessions,
    activeSessionId,
    messages,
    isLoadingSessions,
    isLoadingMessages,
    isSending,
    error,
    createSession,
    selectSession,
    sendMessage,
    renameSession,
    deleteSession,
    // Feature 26 Part 2, task H12 (§P2.6.6/§P2.6.1): these five are what make
    // H10's composer control reachable by a real user. ChatWindow renders the
    // paperclip ONLY when `onAttach` is supplied — until this line existed the
    // button was deliberately never rendered rather than shipped dead.
    attachment,
    uploadAttachment,
    removeAttachment,
    cancelAttachment,
    attachmentCount,
    // Feature 26 task R6: H12 built this and nothing consumed it, so H11's
    // confirmation card and clarification buttons rendered read-only. The
    // handlers below are what make the D4 confirmation gate operable from the UI.
    confirmMatches,
  } = useChatSession();

  // R6. `AttachmentTurnHandlers` (components/chat/MessageBubble.tsx:422) is the
  // contract H11 built the card against; these are the callbacks that satisfy it.
  const [confirmingAttachmentId, setConfirmingAttachmentId] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmedAttachmentIds, setConfirmedAttachmentIds] = useState<string[]>([]);

  const onConfirmMatches = useCallback(
    async (attachmentId: string, invoiceIds: string[]) => {
      setConfirmingAttachmentId(attachmentId);
      setConfirmError(null);
      try {
        await confirmMatches(attachmentId, invoiceIds);
        // Lock the card. The backend rejects any id it did not offer as a
        // candidate (routers/chat_attachments.py), so a second confirm on the
        // same attachment is not merely redundant -- it can 400.
        setConfirmedAttachmentIds((prev) =>
          prev.includes(attachmentId) ? prev : [...prev, attachmentId]
        );
      } catch (e: unknown) {
        // Surfaced inline on the card rather than swallowed: the 400 detail is
        // the only thing that tells a user WHY an invoice could not be confirmed.
        const detail =
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          (e as Error)?.message ??
          "Could not confirm those invoices.";
        setConfirmError(detail);
      } finally {
        setConfirmingAttachmentId(null);
      }
    },
    [confirmMatches]
  );

  // Both of these go back as an ordinary chat message, which is not a shortcut:
  // `MessageCreate` carries only `content` and `attachment_id`, and
  // `_classify_attachment_intent()` is a pure keyword match over the text, so a
  // phrase in the message IS the mechanism for making an intent explicit.
  // MessageBubble has already composed `text` via composeClarificationReply().
  const onClarificationChoice = useCallback(
    async (text: string) => {
      await sendMessage(text);
    },
    [sendMessage]
  );

  // The zero-candidate path. The confirm endpoint takes invoice IDs and rejects
  // anything the matcher did not propose, so a typed invoice NUMBER cannot go
  // there -- it goes back as a message, which is what the backend's own
  // zero-candidate copy asks the user to do.
  const onManualInvoiceEntry = useCallback(
    async (_attachmentId: string, invoiceNumber: string) => {
      await sendMessage(`Compare it against invoice ${invoiceNumber}.`);
    },
    [sendMessage]
  );

  const attachmentHandlers = useMemo(
    () => ({
      onConfirmMatches,
      onManualInvoiceEntry,
      onClarificationChoice,
      confirmingAttachmentId,
      confirmError,
      confirmedAttachmentIds,
    }),
    [
      onConfirmMatches,
      onManualInvoiceEntry,
      onClarificationChoice,
      confirmingAttachmentId,
      confirmError,
      confirmedAttachmentIds,
    ]
  );

  return (
    // WHY -m-8: the Shell component (components/layout/Shell.tsx) wraps
    //   <main> with p-8.  A standard scrollable page works great with that
    //   padding, but the chat layout needs to fill the entire available area
    //   with no outer gutters so the left thread sidebar and pinned input bar
    //   reach the edges.  Negative margin cancels the p-8 without modifying
    //   Shell (which is shared across all pages).
    //
    // WHY h-[calc(100vh-4rem)]: the Header is 4rem (64px) tall.  Subtracting
    //   it from 100vh gives the chat window exactly the remaining vertical
    //   space.  overflow-hidden is set here so that ChatWindow manages its own
    //   internal scroll regions (thread list + message area) — the outer page
    //   should never scroll.
    <div className="-m-8 h-[calc(100vh-4rem)] overflow-hidden">
      <ChatWindow
        sessions={sessions}
        activeSessionId={activeSessionId}
        messages={messages}
        isLoadingSessions={isLoadingSessions}
        isLoadingMessages={isLoadingMessages}
        isSending={isSending}
        error={error}
        onCreateSession={createSession}
        onSelectSession={selectSession}
        onSendMessage={sendMessage}
        onRenameSession={renameSession}
        onDeleteSession={deleteSession}
        onAttach={uploadAttachment}
        attachment={attachment}
        onRemoveAttachment={removeAttachment}
        onCancelAttachment={cancelAttachment}
        attachmentHandlers={attachmentHandlers}
        attachmentCount={attachmentCount}
      />
    </div>
  );
}
