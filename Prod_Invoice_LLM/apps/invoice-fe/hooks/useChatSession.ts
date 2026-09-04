import { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/apiClient";
import {
  MAX_CHAT_ATTACHMENTS_PER_SESSION,
  type AttachmentState,
  type ChatAttachmentSummary,
} from "@/lib/chatAttachments";
import type {
  ChatSession,
  ChatMessage,
  ListSessionsResponse,
  GetSessionResponse,
  SendMessageRequest,
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
  sendMessage: (text: string, attachmentIntent?: "read" | "compare") => Promise<void>;
  clearError: () => void;
  renameSession: (id: string, newTitle: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;

  // --- Feature 26 Part 2, task H12 (§P2.6.6) -------------------------------
  // Everything the composer (H10) needs to become reachable by a real user.
  /** The one document attached to the turn being composed, if any. */
  attachment: AttachmentState | null;
  /** Upload a picked file. XMLHttpRequest, not fetch — see uploadAttachment. */
  uploadAttachment: (file: File) => void;
  /** Detach: the next turn is no longer grounded in this document. */
  removeAttachment: () => void;
  /** Abort the in-flight upload (uploading state only). */
  cancelAttachment: () => void;
  /** How many attachments this SESSION holds. The backend caps at 5 (D3). */
  attachmentCount: number;
  /** The D4 safety gate — records which invoices the user agreed to compare. */
  confirmMatches: (
    attachmentId: string,
    invoiceIds: string[]
  ) => Promise<ChatAttachmentSummary>;
}

// =============================================================================
// Feature 26 Part 2 (H12) — attachment helpers
// =============================================================================

/**
 * Per-session attachment memo, in sessionStorage.
 *
 * WHY THIS EXISTS RATHER THAN A SERVER READ — checked against the router, not
 * assumed. `routers/chat_attachments.py` publishes exactly three endpoints:
 * POST upload, POST confirm-matches, GET by id. There is **no**
 * "list this session's attachments" endpoint, and `ChatMessage` has no
 * `attachment_id` column (only `MessageCreate` carries one, as a request
 * field), so after a refresh the browser has nothing server-side to enumerate.
 *
 * So the id and the session count are remembered here, and the id is then
 * **re-validated against the server** on reload via GET (see
 * `refreshAttachment`) — the memo is a pointer, never a cache of the document's
 * state. If the row is gone (404: swept by the H8 TTL job, session deleted,
 * different tenant) the pointer is dropped and the composer comes back empty.
 *
 * sessionStorage rather than localStorage because "the document I attached in
 * this conversation, in this tab" is exactly a tab-scoped fact; a stale
 * attachment resurrected in a new tab days later is not something the user
 * asked for. The cost is that a genuinely new tab starts with count 0 and no
 * chip — recovered for the chip by the message-derived fallback below, and for
 * the count by the backend's own 409, which is mapped to "session full".
 *
 * Adding a list endpoint would make all of this unnecessary, but that is a
 * backend change and H12 is explicitly frontend-only.
 */
interface AttachmentMemo {
  id?: string;
  count: number;
}

const ATTACHMENT_MEMO_PREFIX = "f26.chat-attachment.";

function readAttachmentMemo(sessionId: string): AttachmentMemo {
  if (typeof window === "undefined") return { count: 0 };
  try {
    const raw = window.sessionStorage.getItem(ATTACHMENT_MEMO_PREFIX + sessionId);
    if (!raw) return { count: 0 };
    const parsed = JSON.parse(raw) as AttachmentMemo;
    return {
      id: typeof parsed.id === "string" ? parsed.id : undefined,
      count: Number.isFinite(parsed.count) ? Number(parsed.count) : 0,
    };
  } catch {
    // A malformed or unavailable store must not break the chat page: the
    // feature degrades to "no memory of the attachment", which is the state
    // this app shipped with until today.
    return { count: 0 };
  }
}

function writeAttachmentMemo(sessionId: string, memo: AttachmentMemo): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      ATTACHMENT_MEMO_PREFIX + sessionId,
      JSON.stringify(memo)
    );
  } catch {
    /* Private-mode / quota. Not worth surfacing — see readAttachmentMemo. */
  }
}

/**
 * Recovers an attachment id from the loaded transcript when the memo is empty
 * (a new tab, or a cleared store).
 *
 * A confirmation turn's payload carries its own `attachment_id`
 * (`build_confirmation_payload()`), so the most recent one names the document
 * this conversation is about. Read defensively through `unknown` rather than
 * through `ChatMessage["attachment_confirmation"]` on purpose: that field lives
 * in `types/chat.ts`, which task H11 owns and is editing in parallel, and a
 * runtime read that cannot break its build is worth more here than the types.
 */
function attachmentIdFromTranscript(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const raw = (messages[i] as unknown as Record<string, unknown>)[
      "attachment_confirmation"
    ];
    if (raw && typeof raw === "object") {
      const id = (raw as { attachment_id?: unknown }).attachment_id;
      if (typeof id === "string" && id) return id;
    }
  }
  return null;
}

/** FastAPI's error envelope is `{"detail": "..."}`; anything else is a shrug. */
function backendDetail(body: string): string | null {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : null;
  } catch {
    return null;
  }
}

/**
 * True when the assistant's reply cannot be acted on without re-sending the
 * SAME attachment on the next turn.
 *
 * DELIBERATE DEVIATION FROM §P2.6.6, stated rather than hidden. That section
 * says `sendMessage` "clears the attachment on success so the next turn is not
 * silently re-grounded on a stale document". Clearing unconditionally breaks
 * D4's own two-turn design: turn 1 returns a match-confirmation payload and no
 * answer, the user confirms, and turn 2 must carry the same `attachment_id` to
 * get the comparison — with the chip already cleared, the user would have to
 * re-upload the document to receive the answer they had just authorised. The
 * clarifying turn (B2) has the identical shape: it answers nothing on purpose
 * and expects the same document back with a disambiguated question.
 *
 * So the attachment is cleared on success EXCEPT after those two turn shapes,
 * which are precisely the ones that produced no answer. The stale-grounding
 * risk §P2.6.6 is protecting against does not apply to them: the document is
 * not stale, it is unanswered.
 */
function turnNeedsSameAttachment(response: unknown): boolean {
  if (!response || typeof response !== "object") return false;
  const record = response as Record<string, unknown>;
  return Boolean(record.attachment_confirmation) || Boolean(record.attachment_clarification);
}

export function useChatSession(): UseChatSessionReturn {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Feature 26 (H12): the document attached to the turn being composed, and how
  // many this session already holds (the backend caps at 5 and 409s past it).
  const [attachment, setAttachment] = useState<AttachmentState | null>(null);
  const [attachmentCount, setAttachmentCount] = useState(0);

  // Keep track of active EventSource instances to prevent memory leaks or orphaned connections
  const activeStreamRef = useRef<EventSource | null>(null);
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);
  // The in-flight upload, so `cancelAttachment()` can abort it and so switching
  // session or unmounting does not leave a request writing into dead state.
  const uploadXhrRef = useRef<XMLHttpRequest | null>(null);
  // `sendMessage` reads the attachment without taking it as a dependency: the
  // composer calls `onSendMessage(text)` with no knowledge of the attachment,
  // and re-creating that callback on every progress tick would re-render the
  // whole thread on each byte of an upload.
  const attachmentRef = useRef<AttachmentState | null>(null);
  useEffect(() => {
    attachmentRef.current = attachment;
  }, [attachment]);

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

  // ---------------------------------------------------------------------------
  // Attachment plumbing (Feature 26 Part 2, task H12 — §P2.6.6)
  // ---------------------------------------------------------------------------

  /**
   * Aborts any in-flight upload. The XHR's own `onabort` clears the chip, so
   * this is safe to call from anywhere (cancel button, session switch, unmount)
   * without duplicating the state reset.
   */
  const abortUpload = useCallback(() => {
    const xhr = uploadXhrRef.current;
    if (!xhr) return;
    uploadXhrRef.current = null;
    // Detach the handlers first: an abort fires `onabort`, and on a session
    // switch that would clear the chip we are about to repopulate from the memo.
    xhr.upload.onprogress = null;
    xhr.upload.onload = null;
    xhr.onload = null;
    xhr.onerror = null;
    xhr.onabort = null;
    xhr.abort();
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupStream();
      abortUpload();
    };
  }, [cleanupStream, abortUpload]);

  /**
   * Re-reads one attachment from the server and puts the composer back into the
   * state it was in — the reload/reattach path (§P2.6.6).
   *
   * This is the read that makes decision D2 worth anything: the backend persists
   * a `ChatAttachment` row rather than keeping the document in session scratch
   * *specifically* so a refresh mid-conversation does not lose it. A 404 (swept,
   * deleted, or another tenant's) is not an error to show the user — it means
   * the pointer is stale, so it is dropped silently.
   */
  const refreshAttachment = useCallback(
    async (sessionId: string, attachmentId: string, knownCount: number) => {
      try {
        const res = await apiClient.get<ChatAttachmentSummary>(
          `/chat/attachments/${attachmentId}`
        );
        const summary = res.data;
        if (!summary?.id) return;
        if (summary.extraction_status === "EXTRACT_FAILED") {
          // The row exists and the file IS stored; the chip must say so rather
          // than pretending nothing was ever uploaded.
          setAttachment({
            status: "failed",
            filename: summary.filename,
            failure: "extraction_failed",
            message: "This document was attached but its text could not be read.",
          });
          return;
        }
        setAttachment({
          status: "ready",
          filename: summary.filename,
          attachment: summary,
        });
        writeAttachmentMemo(sessionId, { id: summary.id, count: knownCount });
      } catch {
        setAttachment(null);
        writeAttachmentMemo(sessionId, { count: knownCount });
      }
    },
    []
  );

  /**
   * Uploads a picked file to `POST /api/chat/sessions/{id}/attachments` and
   * drives `AttachmentState` through its four states.
   *
   * WHY XMLHttpRequest AND NOT fetch — the one non-obvious choice in this file,
   * and §P2.6.2's reason verbatim: `fetch` exposes **no upload progress event**.
   * A 10 MB PDF on a slow connection is a real wait, and a spinner that cannot
   * say how far along it is turns a working upload into an apparently hung one.
   * `xhr.upload.onprogress` is the only browser API that reports it.
   *
   * The state transitions are driven by two different events, deliberately:
   *   `xhr.upload.onload` → the bytes are all sent, so the client's work is over
   *                         and the server's has started → "extracting".
   *   `xhr.onload`        → the response arrived → "ready" or "failed".
   * That split is what makes the "extracting" state honest — extraction runs
   * synchronously INSIDE this request (`_extract_attachment`: a Document
   * Intelligence round trip plus H4's embed step), so between those two events
   * the user is genuinely waiting on the server reading their document.
   */
  // Gap 452: watch one attachment's extraction job. Kept separate from the
  // chat-turn stream on purpose: that one rewrites a message placeholder, this
  // one rewrites the composer chip, and the two must not fight over
  // `activeStreamRef` -- a user can be asking a question while a second
  // document is still being read.
  const extractionStreamRef = useRef<EventSource | null>(null);

  const followExtractionJob = useCallback(
    (jobId: string, attachmentId: string, filename: string) => {
      try {
        extractionStreamRef.current?.close();
      } catch {
        /* nothing to close */
      }

      const finish = async () => {
        try {
          extractionStreamRef.current?.close();
        } catch {
          /* already closed */
        }
        extractionStreamRef.current = null;
        // The completion event carries a summary, but the GET is the contract
        // the chip renders from (preview, confidence, match) -- one source of
        // truth rather than two shapes to keep in step.
        try {
          const res = await apiClient.get<ChatAttachmentSummary>(
            `/chat/attachments/${attachmentId}`
          );
          const row = res.data;
          if (row.extraction_status === "EXTRACT_FAILED") {
            setAttachment({
              status: "failed",
              filename,
              failure: "extraction_failed",
              message: "The document was attached but its text could not be read.",
            });
            return;
          }
          setAttachment({ status: "ready", filename, attachment: row });
        } catch {
          setAttachment({
            status: "failed",
            filename,
            failure: "extraction_failed",
            message: "The document was read but its details could not be loaded. Try re-attaching it.",
          });
        }
      };

      let source: EventSource | null = null;
      try {
        source = new EventSource(`/api/chat/jobs/${jobId}/stream`);
      } catch {
        // No EventSource (an old browser, or a blocked connection): fall back
        // to a single delayed read rather than leaving the chip spinning.
        setTimeout(finish, 30000);
        return;
      }
      extractionStreamRef.current = source;

      source.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as {
            status?: string;
            step?: string;
          };
          if (data.status === "processing" && data.step) {
            setAttachment((prev) =>
              prev && prev.status === "extracting" ? { ...prev, stage: data.step } : prev
            );
            return;
          }
          if (data.status === "completed" || data.status === "failed") {
            void finish();
          }
        } catch {
          /* a malformed event is not worth breaking the wait over */
        }
      };
      source.onerror = () => {
        // The stream dropped. The worker may still finish; read the row rather
        // than guess, after a short grace period for the stream to reconnect.
        setTimeout(() => {
          if (extractionStreamRef.current === source) void finish();
        }, 5000);
      };
    },
    []
  );

  const uploadAttachment = useCallback(
    (file: File) => {
      const sessionId = activeSessionId;
      // No session means no `POST /chat/sessions/{id}/attachments` to make. The
      // paperclip is already disabled in that state; this is the belt to that
      // brace, not the primary guard.
      if (!sessionId) return;

      // One document per turn (§P2.6.1: the file input is deliberately not
      // `multiple`), so a second pick replaces the first rather than racing it.
      abortUpload();
      setAttachment({ status: "uploading", filename: file.name, progress: 0 });

      const form = new FormData();
      // Field name must be "file" — `upload_chat_attachment(file: UploadFile =
      // File(...))` names it, and FastAPI 422s on anything else.
      form.append("file", file, file.name);

      const xhr = new XMLHttpRequest();
      uploadXhrRef.current = xhr;
      xhr.open("POST", `/api/chat/sessions/${sessionId}/attachments`);

      xhr.upload.onprogress = (event: ProgressEvent) => {
        if (!event.lengthComputable || event.total === 0) return;
        const pct = (event.loaded / event.total) * 100;
        setAttachment((prev) =>
          prev && prev.status === "uploading" ? { ...prev, progress: pct } : prev
        );
      };

      xhr.upload.onload = () => {
        setAttachment((prev) =>
          prev && prev.status === "uploading"
            ? { status: "extracting", filename: file.name }
            : prev
        );
      };

      xhr.onload = () => {
        uploadXhrRef.current = null;

        if (xhr.status >= 200 && xhr.status < 300) {
          let summary: ChatAttachmentSummary | null = null;
          try {
            summary = JSON.parse(xhr.responseText) as ChatAttachmentSummary;
          } catch {
            summary = null;
          }
          if (!summary?.id) {
            setAttachment({
              status: "failed",
              filename: file.name,
              failure: "upload_rejected",
              message: "The server accepted the file but returned an unreadable response.",
            });
            return;
          }

          // The row was created either way, so it counts against the 5-per-session
          // cap either way — including when extraction failed.
          const nextCount = Math.min(
            attachmentCount + 1,
            MAX_CHAT_ATTACHMENTS_PER_SESSION
          );
          setAttachmentCount(nextCount);

          if (summary.extraction_status === "EXTRACT_FAILED") {
            // Not the same failure as a rejected upload, and the chip renders
            // them differently: the file IS stored, we just could not read it.
            // No memo id is written — an unreadable document cannot ground a
            // question, so there is nothing worth restoring after a refresh.
            writeAttachmentMemo(sessionId, { count: nextCount });
            setAttachment({
              status: "failed",
              filename: summary.filename || file.name,
              failure: "extraction_failed",
              message: "The document was attached but its text could not be read.",
            });
            return;
          }

          // Feature 26 Phase 3.3 (Gap 452): extraction was queued on the worker.
          // The row exists and counts against the cap, but it is PENDING: keep
          // the chip in the extracting state and follow the job stream, which
          // reports reading -> extracting -> indexing -> matching, then re-read
          // the row so the chip shows the same fields it would have shown from
          // an inline upload.
          if (summary.extraction_job_id && summary.extraction_status === "PENDING") {
            writeAttachmentMemo(sessionId, { id: summary.id, count: nextCount });
            setAttachment({
              status: "extracting",
              filename: summary.filename || file.name,
              stage: "queued",
            });
            followExtractionJob(summary.extraction_job_id, summary.id, summary.filename || file.name);
            return;
          }

          writeAttachmentMemo(sessionId, { id: summary.id, count: nextCount });
          setAttachment({
            status: "ready",
            filename: summary.filename || file.name,
            attachment: summary,
          });
          return;
        }

        // --- Rejected -------------------------------------------------------
        // 413 (>10 MB) / 415 (not a PDF) / 409 (session full) / 404 (session
        // gone) / 5xx. The backend's own `detail` string is shown when there is
        // one: it is written for this exact user and is more specific than
        // anything that could be composed here from a status code.
        const detail = backendDetail(xhr.responseText);
        if (xhr.status === 409) {
          // The server is the authority on the count and has just said the
          // session is full — disable the paperclip rather than letting the
          // user try a seventh time.
          setAttachmentCount(MAX_CHAT_ATTACHMENTS_PER_SESSION);
          writeAttachmentMemo(sessionId, {
            ...readAttachmentMemo(sessionId),
            count: MAX_CHAT_ATTACHMENTS_PER_SESSION,
          });
        }
        setAttachment({
          status: "failed",
          filename: file.name,
          failure: "upload_rejected",
          message:
            detail ??
            (xhr.status === 0
              ? "The upload did not reach the server. Check your connection and try again."
              : `The upload was rejected (HTTP ${xhr.status}).`),
        });
      };

      xhr.onerror = () => {
        uploadXhrRef.current = null;
        setAttachment({
          status: "failed",
          filename: file.name,
          failure: "upload_rejected",
          message: "The upload did not reach the server. Check your connection and try again.",
        });
      };

      xhr.onabort = () => {
        uploadXhrRef.current = null;
        // A cancel is a decision, not a failure — no error row is left behind.
        setAttachment(null);
      };

      xhr.send(form);
    },
    [activeSessionId, attachmentCount, abortUpload]
  );

  /**
   * Detach. The row stays on the server (and keeps counting toward the cap of
   * 5) — this only stops the NEXT turn being grounded in it, which is the point
   * §P2.6.6 is making about stale documents.
   */
  const removeAttachment = useCallback(() => {
    abortUpload();
    setAttachment(null);
    if (activeSessionId) {
      const memo = readAttachmentMemo(activeSessionId);
      writeAttachmentMemo(activeSessionId, { count: memo.count });
    }
  }, [activeSessionId, abortUpload]);

  /** Cancel button on the uploading chip. `onabort` clears the state. */
  const cancelAttachment = useCallback(() => {
    const xhr = uploadXhrRef.current;
    if (!xhr) {
      setAttachment(null);
      return;
    }
    uploadXhrRef.current = null;
    xhr.abort(); // handlers intact here, so `onabort` clears the chip
  }, []);

  /**
   * D4's confirmation gate. Records which of the proposed invoices the user
   * agreed to compare against, so the follow-up turn produces figures instead
   * of another confirmation card.
   *
   * Throws with the backend's own `detail` on a 400 — "Only invoices offered as
   * candidates for this attachment can be confirmed" is exactly what the card
   * must show (§P2.6.3's last bullet), and swallowing it would leave the user
   * clicking a button that appears to do nothing.
   */
  const confirmMatches = useCallback(
    async (attachmentId: string, invoiceIds: string[]): Promise<ChatAttachmentSummary> => {
      try {
        const res = await apiClient.post<ChatAttachmentSummary>(
          `/chat/attachments/${attachmentId}/confirm-matches`,
          { invoice_ids: invoiceIds }
        );
        const summary = res.data;
        // Keep the composer's copy in step, so a chip rendered from it reflects
        // the confirmed set without a refetch.
        setAttachment((prev) =>
          prev && prev.status === "ready" && prev.attachment.id === attachmentId
            ? { ...prev, attachment: summary }
            : prev
        );
        return summary;
      } catch (err) {
        const detail = (
          err as { response?: { data?: { detail?: unknown } } }
        )?.response?.data?.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : "Could not confirm the selected invoices. Please try again."
        );
      }
    },
    []
  );

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
              // Feature 6.1 A3: a `streaming` step carries the answer so far in
              // `details.partial`. It becomes the placeholder's content, rendered
              // as markdown while the bubble is still "processing"; the
              // `completed` event that follows replaces it with the persisted
              // message exactly as before. Any other step is a status line.
              const partial =
                data.step === "streaming" &&
                data.details &&
                typeof data.details === "object" &&
                typeof (data.details as { partial?: unknown }).partial === "string"
                  ? ((data.details as { partial: string }).partial)
                  : null;
              if (partial !== null) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === placeholderId
                      ? { ...m, status: "processing", content: partial, error_message: undefined }
                      : m
                  )
                );
                return;
              }

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
      // Feature 26 (H12): an upload belongs to the session it was started in.
      // Carrying it across a session switch would attach a document to a
      // conversation the user never picked it for.
      abortUpload();
      setAttachment(null);
      const memo = readAttachmentMemo(id);
      setAttachmentCount(memo.count);
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

        // Feature 26 (H12), §P2.6.6's reload/reattach path. The memo is the
        // primary pointer; the transcript is the fallback for a tab that has
        // none (a new tab, a cleared store). Either way the id is only a
        // pointer — the document's real state comes from the GET.
        const attachmentId = memo.id ?? attachmentIdFromTranscript(loadedMessages);
        if (attachmentId) {
          await refreshAttachment(id, attachmentId, memo.count);
        }
      } catch {
        setError("Failed to load messages for this session.");
      } finally {
        setIsLoadingMessages(false);
      }
    },
    [cleanupStream, attachJobListener, abortUpload, refreshAttachment]
  );

  // ---------------------------------------------------------------------------
  // createSession
  // ---------------------------------------------------------------------------
  const createSession = useCallback(async () => {
    cleanupStream();
    // Feature 26 (H12): a fresh conversation starts with no document and an
    // empty per-session count, whatever the previous one held.
    abortUpload();
    setAttachment(null);
    setAttachmentCount(0);
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
    async (text: string, attachmentIntent?: "read" | "compare") => {
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

      // Feature 26 (H12, §P2.6.6): a READY attachment grounds this turn. Any
      // other state does not — an upload still in flight, one that failed, or
      // one whose text could not be read has no id worth sending, and sending
      // one would trip the backend's deterministic pre-route gate (D4) into an
      // attached-document turn with nothing behind it.
      const current = attachmentRef.current;
      const attachedId =
        current && current.status === "ready" ? current.attachment.id : null;

      try {
        // Step 2: POST to proxy → backend
        const body: SendMessageRequest = { content: text.trim() };
        if (attachedId) body.attachment_id = attachedId;
        // Gap 432: only meaningful with an attachment; never sent otherwise.
        if (attachedId && attachmentIntent) body.attachment_intent = attachmentIntent;
        const res = await apiClient.post<SendMessageResponse>(
          `/chat/sessions/${activeSessionId}/message`,
          body
        );

        const responseData = res.data;

        // Clear the attachment on success — EXCEPT after a turn that answered
        // nothing and needs the same document back (see
        // `turnNeedsSameAttachment`). Note that an attachment turn is always
        // synchronous: `post_chat_message()` requires `attachment_id is None`
        // to use the async queue, precisely because the queue carries no
        // attachment and would silently drop it. So the confirmation /
        // clarification payload is right here in `responseData`, not behind a
        // job — no polling is needed to make this decision.
        if (attachedId && !turnNeedsSameAttachment(responseData)) {
          setAttachment(null);
          const memo = readAttachmentMemo(activeSessionId);
          writeAttachmentMemo(activeSessionId, { count: memo.count });
        }

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
        // Feature 26 (H12): `delete_session` deletes the session's attachment
        // rows and their chunks (H4), so the memo now points at nothing.
        if (typeof window !== "undefined") {
          try {
            window.sessionStorage.removeItem(ATTACHMENT_MEMO_PREFIX + id);
          } catch {
            /* see readAttachmentMemo */
          }
        }
        if (activeSessionId === id) {
          abortUpload();
          setAttachment(null);
          setAttachmentCount(0);
          setActiveSessionId(null);
          setMessages([]);
        }
      } catch {
        setError("Failed to delete the chat session.");
      }
    },
    [activeSessionId, cleanupStream, abortUpload]
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
    // Feature 26 Part 2, task H12 (§P2.6.6)
    attachment,
    uploadAttachment,
    removeAttachment,
    cancelAttachment,
    attachmentCount,
    confirmMatches,
  };
}
