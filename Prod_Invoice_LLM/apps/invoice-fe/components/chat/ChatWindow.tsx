// =============================================================================
// FILE: components/chat/ChatWindow.tsx
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: This is the top-level layout component for the /chat page.
//   It orchestrates three sub-sections:
//     1. ThreadSidebar (left, w-64) — lists sessions, "+ New Chat" button
//     2. Message area (flex-1) — shows MessageStream, empty state, or loading
//     3. InputBar (pinned to bottom) — auto-resizing textarea + Send button
//   WHY a separate component instead of putting everything in page.tsx:
//     page.tsx is kept thin (just the hook wiring) so ChatWindow can be
//     tested or reused in a modal context later without importing Next.js
//     page conventions.  All display logic lives here.
//   Sub-components (ThreadSidebar, EmptyState, InputBar) are co-located in
//   this file rather than split into separate files because they are small,
//   tightly coupled to ChatWindow, and never used elsewhere.
// =============================================================================

"use client";

import { useRef, useEffect, useState, KeyboardEvent } from "react";
import {
  MessageSquarePlus,
  MessageSquare,
  Send,
  Loader2,
  BotMessageSquare,
  Trash2,
  Search,
  Pencil,
  Check,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
} from "lucide-react";
import { MessageStream, type AttachmentTurnHandlers } from "./MessageBubble";
import AttachmentChip from "./AttachmentChip";
import {
  CHAT_ATTACHMENT_ACCEPT,
  MAX_CHAT_ATTACHMENTS_PER_SESSION,
  isAttachmentLimitReached,
  validateChatAttachment,
  type AttachmentState,
} from "@/lib/chatAttachments";
import type { ChatSession, ChatMessage } from "@/types/chat";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatSessionDate(dateStr: string): string {
  if (!dateStr) return "";
  const isoStr = dateStr.endsWith("Z") || dateStr.includes("+") ? dateStr : `${dateStr.replace(" ", "T")}Z`;
  const date = new Date(isoStr);
  if (isNaN(date.getTime())) return dateStr;

  const now = new Date();
  const diffHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);
  if (diffHours < 24) {
    return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
  }
  return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

// =============================================================================
// ThreadSidebar — left panel showing the session list with search & rename
// =============================================================================

interface ThreadSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, newTitle: string) => void;
  onDelete: (id: string) => void;
  /** FE Gap 274: hides the whole panel. Undefined = no hide affordance rendered. */
  onHide?: () => void;
}

function ThreadSidebar({
  sessions,
  activeSessionId,
  isLoading,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onHide,
}: ThreadSidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const filteredSessions = sessions.filter((s) =>
    (s.title || "New Chat").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const startRename = (e: React.MouseEvent, s: ChatSession) => {
    e.stopPropagation();
    setEditingId(s.id);
    setEditingTitle(s.title || "New Chat");
  };

  const confirmRename = (e: React.MouseEvent | React.FormEvent) => {
    e.preventDefault();
    if (editingId && editingTitle.trim()) {
      onRename(editingId, editingTitle.trim());
    }
    setEditingId(null);
  };

  return (
    <div className="w-64 shrink-0 border-r border-[#222D3D] flex flex-col h-full bg-[#080B12]/60">
      {/* Header with "+ New Chat" button */}
      <div className="px-4 py-4 border-b border-[#222D3D] flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-200">Conversations</span>
        <div className="flex items-center gap-1.5">
          <button
            id="chat-new-session-btn"
            onClick={onCreate}
            title="New Chat"
            className="
              flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300
              bg-blue-900/20 hover:bg-blue-900/40 border border-blue-800/30
              px-2.5 py-1.5 rounded-lg transition-all duration-150
              focus:outline-none focus:ring-1 focus:ring-blue-600
            "
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            New Chat
          </button>
          {/* FE Gap 274: hide this panel to reclaim width for the message area. */}
          {onHide && (
            <button
              type="button"
              onClick={onHide}
              title="Hide conversation list"
              aria-label="Hide conversation list"
              className="text-slate-500 hover:text-slate-200 p-1.5 rounded-lg hover:bg-[#1E293B]/50 transition-colors"
            >
              <PanelLeftClose className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Search Input Bar (Gap 149) */}
      <div className="px-3 py-2 border-b border-[#222D3D]/60">
        <div className="relative flex items-center">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search threads..."
            className="w-full bg-[#0F172A] border border-[#222D3D] text-xs text-slate-200 placeholder:text-slate-500 pl-8 pr-2.5 py-1.5 rounded-lg outline-none focus:border-blue-500/50"
          />
        </div>
      </div>

      {/* Thread List — three states: loading, empty, populated */}
      <div className="flex-1 overflow-y-auto py-2 space-y-0.5 px-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 text-slate-500 animate-spin" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-500 px-4">
            {searchQuery ? "No matching conversations." : "No conversations yet. Click \"New Chat\" to start."}
          </div>
        ) : (
          filteredSessions.map((session) => {
            const isActive = session.id === activeSessionId;
            const isEditing = session.id === editingId;

            return (
              <div
                key={session.id}
                id={`chat-session-${session.id}`}
                onClick={() => onSelect(session.id)}
                className={`
                  group w-full text-left px-3 py-2.5 rounded-lg cursor-pointer
                  flex items-start justify-between gap-2 transition-all duration-150
                  ${isActive
                    ? "bg-[#1E293B] border border-blue-800/40 text-white"
                    : "text-slate-400 hover:bg-[#1E293B]/40 hover:text-slate-200 border border-transparent"
                  }
                `}
              >
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  <MessageSquare
                    className={`w-4 h-4 mt-0.5 shrink-0 ${isActive ? "text-blue-400" : "text-slate-500 group-hover:text-slate-400"}`}
                  />
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <form onSubmit={confirmRename} className="flex items-center gap-1">
                        <input
                          type="text"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          autoFocus
                          className="w-full bg-slate-900 text-xs text-white px-1.5 py-0.5 rounded border border-blue-500 outline-none"
                        />
                        <button type="submit" className="p-0.5 text-emerald-400 hover:text-emerald-300">
                          <Check className="w-3 h-3" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingId(null);
                          }}
                          className="p-0.5 text-slate-400 hover:text-slate-300"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </form>
                    ) : (
                      <>
                        <p className="text-xs font-medium truncate">
                          {session.title || "New Chat"}
                        </p>
                        <p className="text-[10px] text-slate-500 mt-0.5">
                          {formatSessionDate(session.updated_at || session.created_at)}
                          {session.message_count > 0 && (
                            <span className="ml-1.5">· {session.message_count} msgs</span>
                          )}
                        </p>
                      </>
                    )}
                  </div>
                </div>

                {!isEditing && (
                  <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 shrink-0 transition-opacity">
                    <button
                      type="button"
                      onClick={(e) => startRename(e, session)}
                      title="Rename thread"
                      className="p-1 text-slate-400 hover:text-blue-400 rounded hover:bg-slate-800"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(session.id);
                      }}
                      title="Delete thread"
                      className="p-1 text-slate-400 hover:text-rose-400 rounded hover:bg-slate-800"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// =============================================================================
// EmptyState — shown when no session is selected
// REASON: A blank white (or dark) area with no guidance creates a dead end for
//   new users.  The empty state explains the feature and provides a direct
//   call-to-action to create a session, reducing time-to-first-message.
// =============================================================================

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-5 text-center px-8">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-900/40 to-purple-900/40 border border-blue-800/30 flex items-center justify-center">
        <BotMessageSquare className="w-8 h-8 text-blue-400" />
      </div>
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-1 flex items-center gap-2">
          Invoice AI Chat
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono font-semibold tracking-widest">SAGE</span>
        </h2>
        <p className="text-sm text-slate-500 max-w-xs">
          Ask anything about your invoices — totals, vendors, flagged items, or
          spending trends. The AI will query your data and show the source.
        </p>
      </div>
      <button
        id="chat-empty-new-btn"
        onClick={onCreate}
        className="
          flex items-center gap-2 px-5 py-2.5
          bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium
          rounded-xl transition-all duration-150 shadow-lg shadow-blue-900/30
          focus:outline-none focus:ring-2 focus:ring-blue-500
        "
      >
        <MessageSquarePlus className="w-4 h-4" />
        Start New Chat
      </button>
    </div>
  );
}

// =============================================================================
// SuggestionChips — FE Gap 6: clickable preset queries that auto-fill and
// submit immediately (not just fill the input box), shown only in a fresh,
// empty session -- once the conversation has any messages, the chips would
// just be clutter competing with real chat history.
// =============================================================================

const SUGGESTION_CHIPS = [
  "Total spend this month",
  "Show flagged invoices",
  "Which vendor do I spend the most with?",
  "Any invoices overdue?",
];

function SuggestionChips({ onSelect, disabled }: { onSelect: (text: string) => void; disabled: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
      <p className="text-xs text-slate-500">Try asking:</p>
      <div className="flex flex-wrap justify-center gap-2 max-w-md">
        {SUGGESTION_CHIPS.map((chip) => (
          <button
            key={chip}
            onClick={() => onSelect(chip)}
            disabled={disabled}
            className="
              px-3.5 py-2 text-xs text-slate-300 bg-[#1E293B] border border-[#222D3D]
              rounded-full hover:border-blue-700/60 hover:text-white transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// InputBar — auto-resizing textarea + Send button
// REASON: A standard <input> cannot grow vertically for multi-line messages.
//   A <textarea> with JavaScript height adjustment mimics the UX of modern
//   chat apps (Slack, WhatsApp) where the input grows with content up to a
//   max height, then becomes scrollable.
//   WHY local state for `value` instead of lifting to the hook:
//     The input text is transient — it only matters until Send is pressed.
//     Keeping it local avoids unnecessary re-renders of the entire ChatWindow
//     on every keystroke.
// =============================================================================

interface InputBarProps {
  onSend: (text: string) => void;
  isSending: boolean;
  disabled: boolean; // True when no session is active — prevents orphan messages

  // --- Feature 26 Part 2, task H10 (§P2.6.1) -------------------------------
  // All optional, and the paperclip renders ONLY when `onAttach` is supplied.
  // Task H12 wires these from useChatSession via page.tsx; until it does, the
  // composer is byte-for-byte what it was, rather than growing a button that
  // silently does nothing.
  /** Called with a file that has already passed every client-side guard. */
  onAttach?: (file: File) => void;
  /** The one document attached to the turn being composed, if any. */
  attachment?: AttachmentState | null;
  /** Detach (ready/failed) — clears `attachment`. */
  onRemoveAttachment?: () => void;
  /** Abort the in-flight upload (uploading only). */
  onCancelAttachment?: () => void;
  /** How many attachments this SESSION already holds (backend cap is 5). */
  attachmentCount?: number;
}

function InputBar({
  onSend,
  isSending,
  disabled,
  onAttach,
  attachment = null,
  onRemoveAttachment,
  onCancelAttachment,
  attachmentCount = 0,
}: InputBarProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Client-side rejection copy (size/type/count). Kept local for the same
  // reason `value` is: it matters until the next pick and nowhere else.
  const [attachError, setAttachError] = useState<string | null>(null);

  const sessionFull = isAttachmentLimitReached(attachmentCount);
  const attachDisabled = disabled || isSending || sessionFull;

  // WHY the guards run here as well as on the backend: the backend rejects with
  // 413/415/409, but only after the whole file has been uploaded. Checking
  // first means a user is not made to wait through a doomed upload. The caps
  // are the backend's own constants, mirrored in lib/chatAttachments.ts — a
  // client cap that disagrees with the server is worse than no client cap.
  const handleFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset immediately so picking the SAME file again still fires `change`.
    e.target.value = "";
    if (!file || !onAttach) return;

    const rejection = validateChatAttachment(file, { attachmentCount });
    if (rejection) {
      setAttachError(rejection.message);
      return;
    }
    setAttachError(null);
    onAttach(file);
  };

  // Auto-resize: reset height to "auto" first so shrinkage works correctly
  // (without the reset, removing text wouldn't shrink the box).
  // Capped at 160px (~6 lines) to prevent the input eating the message area.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const handleSend = () => {
    if (!value.trim() || isSending || disabled) return;
    onSend(value.trim());
    setValue("");
    // Reset height back to one row after send
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  // Enter sends; Shift+Enter inserts a newline (standard chat convention)
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault(); // Prevents the newline from being inserted before send
      handleSend();
    }
  };

  return (
    <div className="border-t border-[#222D3D] bg-[#080B12]/80 px-4 py-4">
      {/* Input container — focus-within highlights the border when typing */}
      <div className="bg-[#0F172A] border border-[#222D3D] rounded-2xl px-4 py-3 focus-within:border-blue-700/60 transition-colors duration-200">
        {/* Feature 26 §P2.6.2: the attached document sits INSIDE the composer,
            above the textarea, so it reads as part of the message being
            composed rather than a panel the user can forget about. */}
        {attachment && (
          <div className="mb-2.5">
            <AttachmentChip
              state={attachment}
              onCancel={onCancelAttachment}
              onRemove={onRemoveAttachment}
            />
          </div>
        )}
        <div className="flex items-end gap-3">
        {/* Paperclip + hidden input — the same pattern DropZone.tsx uses
            (a visually hidden <input type="file"> clicked from a real control).
            Rendered only when a handler exists (see InputBarProps). */}
        {onAttach && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              // NOT `multiple` — one document per turn.
              accept={CHAT_ATTACHMENT_ACCEPT}
              onChange={handleFilePicked}
              className="hidden"
              data-testid="chat-attach-input"
            />
            <button
              id="chat-attach-btn" // e2e target, matching chat-input-textarea / chat-send-btn
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={attachDisabled}
              title={
                sessionFull
                  ? `This conversation already has ${MAX_CHAT_ATTACHMENTS_PER_SESSION} attachments, which is the limit.`
                  : "Attach a PDF (purchase order or quotation, max 10 MB)"
              }
              aria-label="Attach a document"
              className="
                shrink-0 w-9 h-9 flex items-center justify-center rounded-xl
                text-slate-400 hover:text-blue-300 hover:bg-[#1E293B]
                disabled:text-slate-600 disabled:hover:bg-transparent
                transition-all duration-150
                focus:outline-none focus:ring-2 focus:ring-blue-500
                disabled:cursor-not-allowed
              "
            >
              <Paperclip className="w-4 h-4" />
            </button>
          </>
        )}
        <textarea
          ref={textareaRef}
          id="chat-input-textarea" // Unique ID for e2e test targeting
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? "Select a chat to start…"
              : "Ask about your invoices… (Enter to send, Shift+Enter for newline)"
          }
          disabled={disabled || isSending}
          rows={1} // Starting height — JS expands it as needed
          className="
            flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-500
            resize-none outline-none leading-relaxed
            disabled:opacity-50 disabled:cursor-not-allowed
            max-h-40 overflow-y-auto
          "
        />
        {/* Send button — shows a spinner while isSending is true */}
        <button
          id="chat-send-btn" // Unique ID for e2e test targeting
          onClick={handleSend}
          disabled={!value.trim() || isSending || disabled}
          title="Send message"
          className="
            shrink-0 w-9 h-9 flex items-center justify-center rounded-xl
            bg-blue-600 hover:bg-blue-500 disabled:bg-[#1E293B] disabled:text-slate-500
            text-white transition-all duration-150
            focus:outline-none focus:ring-2 focus:ring-blue-500
            disabled:cursor-not-allowed
          "
        >
          {/* WHY Loader2 instead of hiding the button: keeps the layout stable
              and signals to the user that their message is being processed. */}
          {isSending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
        </div>
      </div>
      {/* Client-side guard rejection (size / type / per-session count). Shown
          here rather than as a toast so it sits next to the control that
          produced it. */}
      {attachError && (
        <p
          data-testid="chat-attach-error"
          className="mt-2 text-[11px] text-rose-300 bg-rose-950/25 border border-rose-800/40 rounded-lg px-2.5 py-1.5"
        >
          {attachError}
        </p>
      )}
      {/* Disclaimer — important for a financial AI tool to set expectations */}
      <p className="text-[10px] text-slate-600 mt-2 text-center">
        AI may make mistakes. Always verify critical figures against source invoices.
      </p>
    </div>
  );
}

// =============================================================================
// ChatWindow — main exported component, composed of the above sub-components
// All props flow down from useChatSession via page.tsx (no prop drilling beyond
// one level — ChatWindow → sub-components — which is acceptable at this scale).
// =============================================================================

interface ChatWindowProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  isLoadingSessions: boolean;
  isLoadingMessages: boolean;
  isSending: boolean;
  error: string | null;
  onCreateSession: () => void;
  onSelectSession: (id: string) => void;
  onSendMessage: (text: string) => void;
  onRenameSession: (id: string, newTitle: string) => void;
  onDeleteSession: (id: string) => void;

  // --- Feature 26 Part 2, task H10 (§P2.6.1) -------------------------------
  // Optional and threaded straight through to InputBar. Task H12 supplies them
  // from useChatSession via page.tsx:
  //   onAttach            → uploadAttachment(file): XHR POST to
  //                         /api/chat/sessions/{id}/attachments, driving
  //                         AttachmentState through uploading → extracting →
  //                         ready | failed.
  //   attachment          → that AttachmentState (null when nothing attached).
  //   onRemoveAttachment  → clears it, so the next turn is not silently
  //                         re-grounded on a stale document.
  //   onCancelAttachment  → aborts the in-flight XHR.
  //   attachmentCount     → count of attachments already on the SESSION (not
  //                         the turn), which is what the backend's 409 counts.
  onAttach?: (file: File) => void;
  attachment?: AttachmentState | null;
  onRemoveAttachment?: () => void;
  onCancelAttachment?: () => void;
  attachmentCount?: number;
  // Feature 26 task H16/R6. H11 built the confirmation card, the clarification
  // buttons and the manual-entry field behind this prop, and H12 built the
  // callbacks that feed it -- but the two shipped in parallel and neither could
  // thread a prop the other had not merged yet, so `<MessageStream>` below was
  // rendered without it and every one of those controls stayed dark. Optional,
  // matching H10's precedent: absent means the bubbles render read-only rather
  // than showing a button that does nothing.
  attachmentHandlers?: AttachmentTurnHandlers;
}

export default function ChatWindow({
  sessions,
  activeSessionId,
  messages,
  isLoadingSessions,
  isLoadingMessages,
  isSending,
  error,
  onCreateSession,
  onSelectSession,
  onSendMessage,
  onRenameSession,
  onDeleteSession,
  onAttach,
  attachment = null,
  onRemoveAttachment,
  onCancelAttachment,
  attachmentCount = 0,
  attachmentHandlers,
}: ChatWindowProps) {
  const hasActiveSession = !!activeSessionId;

  // FE Gap 274: the thread list can be hidden entirely (unlike the main
  // app Sidebar's icon-only collapse, per Gap 273 -- the chat window is
  // fully usable without it visible at all). Persisted the same way.
  const [sidebarHidden, setSidebarHidden] = useState(false);
  useEffect(() => {
    if (window.localStorage.getItem("chat-thread-sidebar-hidden") === "true") {
      setSidebarHidden(true);
    }
  }, []);
  const setSidebarHiddenPersisted = (hidden: boolean) => {
    setSidebarHidden(hidden);
    window.localStorage.setItem("chat-thread-sidebar-hidden", String(hidden));
  };

  return (
    // h-full: fills the container set by page.tsx (100vh minus header height)
    // overflow-hidden: the scroll is managed inside MessageStream and ThreadSidebar,
    //   not on this container — prevents double scrollbars.
    <div className="flex h-full overflow-hidden">
      {/* Left: Thread Sidebar (FE Gap 274: omitted entirely when hidden) */}
      {!sidebarHidden && (
        <ThreadSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          isLoading={isLoadingSessions}
          onSelect={onSelectSession}
          onCreate={onCreateSession}
          onRename={onRenameSession}
          onDelete={onDeleteSession}
          onHide={() => setSidebarHiddenPersisted(true)}
        />
      )}

      {/* Right: Chat Area — flex column so input bar is always pinned to bottom */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Slim agent strip -- deliberately not a full PageHeader: this layout
            fills the entire viewport with no outer gutters (see page.tsx's
            -m-8 comment), so anything taller than one compact row would eat
            directly into message-area space. */}
        <div className="px-4 py-1.5 border-b border-[#222D3D] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-1.5">
            {/* FE Gap 274: brings the thread list back once hidden. */}
            {sidebarHidden && (
              <button
                type="button"
                onClick={() => setSidebarHiddenPersisted(false)}
                title="Show conversation list"
                aria-label="Show conversation list"
                className="text-slate-500 hover:text-slate-200 p-1 -ml-1 mr-0.5 rounded hover:bg-[#1E293B]/50 transition-colors"
              >
                <PanelLeftOpen className="w-3.5 h-3.5" />
              </button>
            )}
            <span className="text-xs leading-none not-italic">🧙</span>
            <span className="text-[10px] font-mono font-semibold text-[#6366F1] tracking-wide">SAGE</span>
            <span className="text-[10px] text-slate-500">— Conversational Insights</span>
          </div>
          {hasActiveSession && (
            <button
              onClick={() => onDeleteSession(activeSessionId)}
              title="Delete conversation"
              className="flex items-center gap-1 text-[10px] text-rose-400 hover:text-rose-300 font-semibold px-2 py-0.5 border border-rose-800/30 rounded bg-rose-950/15 hover:bg-rose-950/30 transition-all duration-150"
            >
              <Trash2 className="w-3 h-3" />
              {/* FE Gap 177 (N-19): labelled "Clear Chat" but wired to the same
                  onDeleteSession handler as the sidebar trash icon -- it deletes
                  the whole thread. There is no clear-messages-keep-thread path in
                  the FE or backend, so the label was corrected to match behaviour
                  rather than a new capability being invented. */}
              Delete Chat
            </button>
          )}
        </div>

        {/* Error Banner — shown when the hook sets a non-null error string */}
        {error && (
          <div className="px-4 py-2.5 bg-red-950/40 border-b border-red-800/40 text-xs text-red-300 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
            {error}
          </div>
        )}

        {/* Message Area — three states: no session, loading, messages */}
        <div className="flex-1 overflow-y-auto">
          {!hasActiveSession ? (
            <EmptyState onCreate={onCreateSession} />
          ) : isLoadingMessages ? (
            // Loading state while selectSession fetches message history
            <div className="flex items-center justify-center h-full gap-2 text-slate-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading messages…
            </div>
          ) : messages.length === 0 ? (
            // FE Gap 6: a fresh, empty session shows suggestion chips instead
            // of a blank area -- messages.length flips to 1 as soon as the
            // optimistic user bubble is added, so this never flickers mid-send.
            <SuggestionChips onSelect={onSendMessage} disabled={isSending} />
          ) : (
            <MessageStream
              messages={messages}
              isSending={isSending}
              attachmentHandlers={attachmentHandlers}
            />
          )}
        </div>

        {/* Input Bar — always rendered but disabled when no session is active */}
        <InputBar
          onSend={onSendMessage}
          isSending={isSending}
          disabled={!hasActiveSession}
          onAttach={onAttach}
          attachment={attachment}
          onRemoveAttachment={onRemoveAttachment}
          onCancelAttachment={onCancelAttachment}
          attachmentCount={attachmentCount}
        />
      </div>
    </div>
  );
}
