"use client";
// WHY "use client": this page uses useChatSession which calls useState/useEffect
//   and calls apiClient (browser Axios).  Next.js requires the client directive
//   on any component that uses browser-only React hooks or browser APIs.

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
  } = useChatSession();

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
        attachmentCount={attachmentCount}
      />
    </div>
  );
}
