// =============================================================================
// FILE: hooks/useChatSession.ts
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: All chat state (sessions list, active thread, messages, loading
//   flags, errors) needs to be managed in one place so that ChatWindow, the
//   thread sidebar, and the message stream always stay in sync.  A custom hook
//   was chosen over a global store (Zustand/Context) because the chat state is
//   only needed on the /chat page — no cross-page sharing is required.
//   Uses the existing apiClient (Axios instance with baseURL: "/api") so all
//   calls are same-origin and the auth header is forwarded server-side.
// =============================================================================

import { useState, useEffect, useCallback } from "react";
import { apiClient } from "@/lib/apiClient";
import type {
  ChatSession,
  ChatMessage,
  ListSessionsResponse,
  GetSessionResponse,
  SendMessageResponse,
} from "@/types/chat";

// Return type is explicitly exported so ChatWindow and page.tsx can type
// the props they receive from this hook without re-declaring the shape.
export interface UseChatSessionReturn {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  isLoadingSessions: boolean;    // Controls the spinner in the thread sidebar
  isLoadingMessages: boolean;    // Controls the spinner in the message area
  isSending: boolean;            // Controls the send button spinner + disables input
  error: string | null;          // Shown in the red error banner at the top of the chat area
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  clearError: () => void;
  renameSession: (id: string, newTitle: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
}

export function useChatSession(): UseChatSessionReturn {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // fetchSessions
  // WHY: Populate the left sidebar thread list as soon as the /chat page mounts.
  //   Wrapped in useCallback so it has a stable reference for the useEffect dep
  //   array — prevents an infinite re-render loop.
  //   Silently swallows the error (sets an empty array) because a missing
  //   sessions list is non-fatal; the user can still create a new session.
  // ---------------------------------------------------------------------------
  const fetchSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    try {
      const res = await apiClient.get<ListSessionsResponse>("/chat/sessions");
      setSessions(res.data ?? []);
    } catch {
      // Gracefully handle backend being offline during local development.
      // The empty array keeps the UI functional — user can still start a chat.
      setSessions([]);
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  // Run once on mount — analogous to componentDidMount
  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  // ---------------------------------------------------------------------------
  // selectSession
  // WHY: When the user clicks a thread in the sidebar, we need to load its
  //   full message history from the backend.  We clear messages first so the
  //   previous thread's content doesn't flash while the new one loads.
  //   isLoadingMessages triggers the Loader2 spinner in the message area.
  // ---------------------------------------------------------------------------
  const selectSession = useCallback(async (id: string) => {
    setActiveSessionId(id);
    setMessages([]);          // Clear previous thread's messages immediately
    setIsLoadingMessages(true);
    setError(null);
    try {
      const res = await apiClient.get<GetSessionResponse>(`/chat/sessions/${id}`);
      setMessages(res.data ?? []);
    } catch {
      setError("Failed to load messages for this session.");
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // createSession
  // WHY: Creates a new empty thread on the backend, prepends it to the local
  //   sessions list (so it appears at the top of the sidebar immediately), and
  //   sets it as active.  No optimistic ID is used here — we wait for the
  //   backend UUID because the real ID is needed for subsequent message POSTs.
  // ---------------------------------------------------------------------------
  const createSession = useCallback(async () => {
    setError(null);
    try {
      const res = await apiClient.post<ChatSession>("/chat/sessions", {
        title: "New Chat",
      });
      const newSession = res.data;
      // Prepend so the newest session always appears at the top of the list
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
      setMessages([]); // Start with an empty message area for the new thread
    } catch {
      setError("Could not create a new chat session.");
    }
  }, []);

  // ---------------------------------------------------------------------------
  // sendMessage
  // WHY: The UX requirement is zero perceived latency — the user's bubble must
  //   appear instantly.  We achieve this with an optimistic update:
  //     1. Append a fake user message immediately (using a temp ID).
  //     2. POST the message to the backend (may take 2-10s for LLM response).
  //     3. Append the real assistant message from the response.
  //   If the POST fails, we roll back step 1 by filtering out the temp message,
  //   and show an error banner.
  //   isSending guard prevents double-sends if the user clicks quickly.
  //   Session title is updated optimistically from "New Chat" to the first
  //   message text (truncated to 48 chars) so the sidebar label is meaningful.
  // ---------------------------------------------------------------------------
  const sendMessage = useCallback(
    async (text: string) => {
      // Guard: must have an active session and non-empty text, not already sending
      if (!activeSessionId || !text.trim() || isSending) return;
      setError(null);

      // Step 1: Optimistic user bubble — shows immediately without waiting for network
      const optimisticUserMsg: ChatMessage = {
        id: `optimistic-${Date.now()}`, // Temporary ID — never sent to the backend
        session_id: activeSessionId,
        role: "user",
        content: text.trim(),
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMsg]);
      setIsSending(true); // Show typing indicator + disable input

      try {
        // Step 2: POST to proxy → backend run_query_agent()
        const res = await apiClient.post<SendMessageResponse>(
          `/chat/sessions/${activeSessionId}/message`,
          { content: text.trim() }
        );

        // Step 3: Append the real assistant message (may include generated_sql + citations)
        const assistantMsg = res.data;
        setMessages((prev) => [...prev, assistantMsg]);

        // Optimistically rename "New Chat" or placeholder to the first message text for sidebar legibility
        setSessions((prev) =>
          prev.map((s) => {
            if (s.id === activeSessionId && (s.title === "New Chat" || s.title.startsWith("Chat Session -"))) {
              const words = text.trim().split(/\s+/);
              let newTitle = words.slice(0, 6).join(" ");
              if (words.length > 6) {
                newTitle += "...";
              }
              return { ...s, title: newTitle };
            }
            return s;
          })
        );
      } catch {
        setError("Failed to send message. Please try again.");
        // Roll back: remove the optimistic user bubble to avoid a dangling unanswered message
        setMessages((prev) =>
          prev.filter((m) => m.id !== optimisticUserMsg.id)
        );
      } finally {
        setIsSending(false); // Re-enable input + hide typing indicator
      }
    },
    [activeSessionId, isSending]
  );

  const renameSession = useCallback(async (id: string, newTitle: string) => {
    if (!newTitle.trim()) return;
    setError(null);
    try {
      await apiClient.put(`/chat/sessions/${id}`, { title: newTitle.trim() });
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: newTitle.trim() } : s))
      );
    } catch {
      // Fallback: update local state if backend route returns 404/501
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: newTitle.trim() } : s))
      );
    }
  }, []);

  const deleteSession = useCallback(async (id: string) => {
    setError(null);
    try {
      await apiClient.delete(`/chat/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch {
      setError("Failed to delete the chat session.");
    }
  }, [activeSessionId]);

  // Allows the error banner's dismiss button (or future logic) to clear state
  const clearError = useCallback(() => setError(null), []);

  return {
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
    clearError,
    renameSession,
    deleteSession,
  };
}
