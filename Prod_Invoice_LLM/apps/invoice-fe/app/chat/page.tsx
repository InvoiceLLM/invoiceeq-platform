"use client";
// WHY "use client": this page uses useChatSession which calls useState/useEffect
//   and calls apiClient (browser Axios).  Next.js requires the client directive
//   on any component that uses browser-only React hooks or browser APIs.

import { useChatSession } from "@/hooks/useChatSession";
import ChatWindow from "@/components/chat/ChatWindow";

export default function ChatPage() {
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
      />
    </div>
  );
}
