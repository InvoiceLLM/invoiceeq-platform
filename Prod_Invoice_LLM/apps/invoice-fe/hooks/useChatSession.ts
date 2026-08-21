import { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/apiClient";
import type {
  ChatSession,
  ChatMessage,
  ListSessionsResponse,
  GetSessionResponse,
  SendMessageResponse,
  ChatJobResponse,
  ChatStreamEvent,
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

  // Keep track of active EventSource instances to prevent memory leaks or orphaned connections
  const activeStreamRef = useRef<EventSource | null>(null);
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const cleanupStream = useCallback(() => {
    if (activeStreamRef.current) {
      activeStreamRef.current.close();
      activeStreamRef.current = null;
    }
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => cleanupStream();
  }, [cleanupStream]);

  // ---------------------------------------------------------------------------
  // fetchSessions
  // ---------------------------------------------------------------------------
  const fetchSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    try {
      const res = await apiClient.get<ListSessionsResponse>("/chat/sessions");
      setSessions(res.data ?? []);
    } catch {
      setSessions([]);
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  // ---------------------------------------------------------------------------
  // attachJobListener (Gap 280: SSE Streaming + Polling Fallback)
  // ---------------------------------------------------------------------------
  const attachJobListener = useCallback(
    (jobId: string, placeholderId: string) => {
      cleanupStream();

      let eventSource: EventSource | null = null;
      try {
        eventSource = new EventSource(`/api/chat/jobs/${jobId}/stream`);
        activeStreamRef.current = eventSource;

        eventSource.onmessage = (e) => {
          try {
            const data: ChatStreamEvent = JSON.parse(e.data);

            if (data.status === "processing") {
              const stepDetail =
                typeof data.details === "string"
                  ? data.details
                  : data.details?.message || data.step || "Analyzing...";

              setMessages((prev) =>
                prev.map((m) =>
                  m.id === placeholderId
                    ? {
                        ...m,
                        status: "processing",
                        error_message: stepDetail,
                      }
                    : m
                )
              );
            } else if (data.status === "completed" && data.result) {
              const completedMsg: ChatMessage = {
                ...data.result,
                status: "completed",
              };
              setMessages((prev) =>
                prev.map((m) => (m.id === placeholderId ? completedMsg : m))
              );
              cleanupStream();
              setIsSending(false);
            } else if (data.status === "failed") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === placeholderId
                    ? {
                        ...m,
                        status: "failed",
                        content:
                          data.error ||
                          "Sorry, something went wrong processing your request.",
                        error_message: data.error,
                      }
                    : m
                )
              );
              cleanupStream();
              setIsSending(false);
            }
          } catch {
            // Ignore JSON parse errors for non-standard frames
          }
        };

        eventSource.onerror = () => {
          // Fallback to polling if SSE fails
          cleanupStream();
          startPollingFallback(jobId, placeholderId);
        };
      } catch {
        startPollingFallback(jobId, placeholderId);
      }

      function startPollingFallback(jId: string, pId: string) {
        let attempts = 0;
        const maxAttempts = 60; // 60 * 2s = 120s max

        pollingTimerRef.current = setInterval(async () => {
          attempts++;
          try {
            const res = await apiClient.get<ChatStreamEvent>(`/chat/jobs/${jId}/status`);
            const statusData = res.data;

            if (statusData.status === "processing") {
              const stepDetail =
                typeof statusData.details === "string"
                  ? statusData.details
                  : statusData.details?.message || statusData.step || "Analyzing...";

              setMessages((prev) =>
                prev.map((m) =>
                  m.id === pId
                    ? { ...m, status: "processing", error_message: stepDetail }
                    : m
                )
              );
            } else if (statusData.status === "completed" && statusData.result) {
              const completedMsg: ChatMessage = {
                ...statusData.result,
                status: "completed",
              };
              setMessages((prev) =>
                prev.map((m) => (m.id === pId ? completedMsg : m))
              );
              cleanupStream();
              setIsSending(false);
            } else if (statusData.status === "failed" || attempts >= maxAttempts) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === pId
                    ? {
                        ...m,
                        status: "failed",
                        content:
                          statusData.error ||
                          "Query took too long or failed. Please retry.",
                      }
                    : m
                )
              );
              cleanupStream();
              setIsSending(false);
            }
          } catch {
            if (attempts >= maxAttempts) {
              cleanupStream();
              setIsSending(false);
            }
          }
        }, 2000);
      }
    },
    [cleanupStream]
  );

  // ---------------------------------------------------------------------------
  // selectSession
  // ---------------------------------------------------------------------------
  const selectSession = useCallback(
    async (id: string) => {
      cleanupStream();
      setActiveSessionId(id);
      setMessages([]);
      setIsLoadingMessages(true);
      setError(null);
      try {
        const res = await apiClient.get<GetSessionResponse>(`/chat/sessions/${id}`);
        const loadedMessages = res.data ?? [];
        setMessages(loadedMessages);

        // Gap 280: If the last message is still queued/processing, resume streaming listener
        const lastMsg = loadedMessages[loadedMessages.length - 1];
        if (
          lastMsg &&
          lastMsg.role === "assistant" &&
          (lastMsg.status === "queued" || lastMsg.status === "processing") &&
          lastMsg.job_id
        ) {
          setIsSending(true);
          attachJobListener(lastMsg.job_id, lastMsg.id);
        }
      } catch {
        setError("Failed to load messages for this session.");
      } finally {
        setIsLoadingMessages(false);
      }
    },
    [cleanupStream, attachJobListener]
  );

  // ---------------------------------------------------------------------------
  // createSession
  // ---------------------------------------------------------------------------
  const createSession = useCallback(async () => {
    cleanupStream();
    setError(null);
    try {
      const res = await apiClient.post<ChatSession>("/chat/sessions", {
        title: "New Chat",
      });
      const newSession = res.data;
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
      setMessages([]);
    } catch {
      setError("Could not create a new chat session.");
    }
  }, [cleanupStream]);

  // ---------------------------------------------------------------------------
  // sendMessage
  // ---------------------------------------------------------------------------
  const sendMessage = useCallback(
    async (text: string) => {
      if (!activeSessionId || !text.trim() || isSending) return;
      setError(null);

      // Step 1: Optimistic user bubble
      const optimisticUserMsg: ChatMessage = {
        id: `optimistic-${Date.now()}`,
        session_id: activeSessionId,
        role: "user",
        content: text.trim(),
        status: "queued",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMsg]);
      setIsSending(true);

      try {
        // Step 2: POST to proxy → backend
        const res = await apiClient.post<SendMessageResponse>(
          `/chat/sessions/${activeSessionId}/message`,
          { content: text.trim() }
        );

        const responseData = res.data;

        // Gap 280: Check if response is asynchronous ChatJobResponse (202)
        if ("job_id" in responseData && responseData.job_id) {
          const placeholderId = `job-${responseData.job_id}`;
          const placeholderAssistantMsg: ChatMessage = {
            id: placeholderId,
            session_id: activeSessionId,
            role: "assistant",
            content: "",
            status: "queued",
            job_id: responseData.job_id,
            error_message: "Queued in line (Slot reserved)...",
            created_at: new Date().toISOString(),
          };

          setMessages((prev) => [...prev, placeholderAssistantMsg]);
          attachJobListener(responseData.job_id, placeholderId);
        } else {
          // Synchronous fallback response
          const assistantMsg = responseData as ChatMessage;
          setMessages((prev) => [...prev, assistantMsg]);
          setIsSending(false);
        }

        // Optimistically update session title in sidebar
        setSessions((prev) =>
          prev.map((s) => {
            if (
              s.id === activeSessionId &&
              (s.title === "New Chat" || s.title.startsWith("Chat Session -"))
            ) {
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
        setMessages((prev) =>
          prev.filter((m) => m.id !== optimisticUserMsg.id)
        );
        setIsSending(false);
      }
    },
    [activeSessionId, isSending, attachJobListener]
  );

  // ---------------------------------------------------------------------------
  // renameSession
  // ---------------------------------------------------------------------------
  const renameSession = useCallback(async (id: string, newTitle: string) => {
    const title = newTitle.trim();
    if (!title) return;
    setError(null);
    try {
      const res = await apiClient.put<Pick<ChatSession, "id" | "title">>(
        `/chat/sessions/${id}`,
        { title }
      );
      const savedTitle = res.data?.title ?? title;
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: savedTitle } : s))
      );
    } catch {
      setError("Failed to rename this chat session.");
    }
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      cleanupStream();
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
    },
    [activeSessionId, cleanupStream]
  );

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
