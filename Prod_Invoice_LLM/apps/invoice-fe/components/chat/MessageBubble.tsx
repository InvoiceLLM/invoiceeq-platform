// =============================================================================
// FILE: components/chat/MessageBubble.tsx
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: Each message in the chat thread needs to be rendered with
//   role-specific styling, markdown formatting, and optional sub-components
//   (citation pills, SQL drawer).  This file exports two components:
//     MessageBubble — renders a single ChatMessage
//     MessageStream — renders the full ordered list with auto-scroll and a
//                     typing indicator while the backend is processing
//   WHY inline markdown renderer instead of react-markdown:
//     The project has no react-markdown installed and adding an ES-module
//     dependency requires Next.js transpilePackages config.  The backend
//     assistant responses only use **bold**, *italic*, and `inline code` —
//     a small regex-based renderer handles all three without any package
//     install, keeping the bundle lean.
// =============================================================================

"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, User, ThumbsUp, ThumbsDown } from "lucide-react";
import CitationPill from "./CitationPill";
import SqlAuditDrawer from "./SqlAuditDrawer";
import ThumbsDownTriage from "./ThumbsDownTriage";
import { apiClient } from "@/lib/apiClient";
import { useAuth } from "@/hooks/useAuth";
import type { ChatMessage } from "@/types/chat";

// =============================================================================
// FeedbackVote — Gap 54, extended by Feature 14 (FE) / Feature 18 (BE).
//
// Thumbs-**up** is unchanged and still signal-only: it records a vote and does
// nothing else, exactly as Gap 54 specified.
//
// Thumbs-**down** is no longer a dead end. It now opens the triage flow
// (`ThumbsDownTriage`), which asks *why* the answer was bad and routes on the
// answer: a wrong value is diffed against the stored data automatically, a
// wrong interpretation becomes a structured category pick, and bad tone goes to
// the tenant's chat style rather than becoming a rule at all. The vote itself is
// still written first, by the triage flow's own `submitFeedback` call — so a
// user who abandons the dialog has still registered the complaint.
//
// Clicking the currently-active thumb again clears the vote (DELETE) rather
// than re-sending it, giving a normal toggle interaction. Clearing a
// thumbs-down does not re-open triage.
// =============================================================================
function FeedbackVote({ messageId, initialVote }: { messageId: string; initialVote: "up" | "down" | null | undefined }) {
  const [vote, setVote] = useState<"up" | "down" | null>(initialVote ?? null);
  const [submitting, setSubmitting] = useState(false);
  const [triageOpen, setTriageOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const { canTrain } = useAuth();

  const handleUp = async () => {
    if (submitting) return;
    setSubmitting(true);
    const clearing = vote === "up";
    const previous = vote;
    setVote(clearing ? null : "up"); // optimistic
    try {
      if (clearing) {
        await apiClient.delete(`/chat/messages/${messageId}/feedback`);
      } else {
        await apiClient.put(`/chat/messages/${messageId}/feedback`, { vote: "up" });
      }
    } catch (err) {
      console.error("Failed to save chat feedback:", err);
      setVote(previous); // roll back on failure
    } finally {
      setSubmitting(false);
    }
  };

  const handleDown = async () => {
    if (submitting) return;
    // Clicking an active thumbs-down clears it, same toggle semantics as before.
    if (vote === "down") {
      setSubmitting(true);
      setVote(null);
      try {
        await apiClient.delete(`/chat/messages/${messageId}/feedback`);
      } catch (err) {
        console.error("Failed to clear chat feedback:", err);
        setVote("down");
      } finally {
        setSubmitting(false);
      }
      return;
    }
    // Optimistic: the triage flow writes the real vote (with its reason) as its
    // own first step, so the mark is correct even if the user closes the dialog
    // at the reason picker.
    setVote("down");
    setTriageOpen(true);
  };

  return (
    <>
      <div className="flex items-center gap-1 px-1">
        <button
          onClick={handleUp}
          disabled={submitting}
          title="Good answer"
          className={`p-1 rounded transition-colors disabled:opacity-50 ${
            vote === "up" ? "text-emerald-400 bg-emerald-500/10" : "text-slate-600 hover:text-slate-400"
          }`}
        >
          <ThumbsUp className="w-3 h-3" />
        </button>
        <button
          onClick={handleDown}
          disabled={submitting}
          title="Bad answer"
          data-testid="chat-thumbs-down"
          className={`p-1 rounded transition-colors disabled:opacity-50 ${
            vote === "down" ? "text-rose-400 bg-rose-500/10" : "text-slate-600 hover:text-slate-400"
          }`}
        >
          <ThumbsDown className="w-3 h-3" />
        </button>
        {toast && <span className="text-[10px] text-emerald-400 ml-1">{toast}</span>}
      </div>

      <ThumbsDownTriage
        isOpen={triageOpen}
        messageId={messageId}
        canTrain={canTrain}
        onClose={() => setTriageOpen(false)}
        onResolved={(summary) => {
          setToast(summary);
          setTimeout(() => setToast(null), 6000);
        }}
      />
    </>
  );
}

// =============================================================================
// renderMarkdown — lightweight inline markdown processor
// WHY: Covers the three patterns the backend LLM realistically produces:
//   **bold text** → <strong>
//   *italic text* → <em>
//   `inline code` → <code> styled with the same dark bg/green text as the
//                   SQL code block for visual consistency
// Each call to text.split("\n") creates a line-level array; regex then
// processes inline tokens within each line.  The result is a React node
// array rendered directly inside the assistant bubble.
// =============================================================================
function renderMarkdown(text: string): React.ReactNode[] {
  return text.split("\n").map((line, lineIdx) => {
    const parts: React.ReactNode[] = [];
    // Matches **bold**, `code`, and *italic* in a single pass
    const pattern = /(\*\*(.+?)\*\*|`([^`]+)`|\*(.+?)\*)/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = pattern.exec(line)) !== null) {
      // Push any plain text that appeared before this match
      if (match.index > lastIndex) {
        parts.push(line.slice(lastIndex, match.index));
      }

      if (match[2]) {
        // **bold** — white + semibold to stand out against the muted bubble text
        parts.push(
          <strong key={`${lineIdx}-${match.index}-b`} className="text-white font-semibold">
            {match[2]}
          </strong>
        );
      } else if (match[3]) {
        // `inline code` — same palette as SqlAuditDrawer for visual consistency
        parts.push(
          <code
            key={`${lineIdx}-${match.index}-c`}
            className="bg-[#0B0F19] text-[#10B981] px-1.5 py-0.5 rounded text-[11px] font-mono border border-[#222D3D]"
          >
            {match[3]}
          </code>
        );
      } else if (match[4]) {
        // *italic*
        parts.push(
          <em key={`${lineIdx}-${match.index}-i`} className="text-slate-300 italic">
            {match[4]}
          </em>
        );
      }
      lastIndex = match.index + match[0].length;
    }

    // Push any trailing plain text after the last match
    if (lastIndex < line.length) {
      parts.push(line.slice(lastIndex));
    }

    // WHY \u00A0 (non-breaking space): an empty <span> collapses to zero height,
    // losing the visual line break.  A NBSP preserves the vertical rhythm.
    return (
      <span key={lineIdx} className={lineIdx > 0 ? "block mt-1" : "block"}>
        {parts.length > 0 ? parts : line || "\u00A0"}
      </span>
    );
  });
}

// =============================================================================
// MessageBubble — single message renderer
// =============================================================================

interface MessageBubbleProps {
  message: ChatMessage;
}

function formatMessageTimestamp(dateStr?: string): string {
  if (!dateStr) return "";
  const isoStr = dateStr.endsWith("Z") || dateStr.includes("+") ? dateStr : `${dateStr.replace(" ", "T")}Z`;
  const date = new Date(isoStr);
  if (isNaN(date.getTime())) return dateStr;

  const datePart = date.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
  const timePart = date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
  return `${datePart}, ${timePart}`;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const formattedTime = formatMessageTimestamp(message.created_at);

  return (
    // flex-row-reverse for user messages pushes avatar + bubble to the right
    <div
      className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* ── Avatar ─────────────────────────────────────────────────────── */}
      {/* WHY different colors: blue = human, purple = AI — standard
          convention that helps users quickly scan who said what. */}
      <div
        className={`
          shrink-0 w-8 h-8 rounded-full flex items-center justify-center
          ${isUser
            ? "bg-blue-600/30 border border-blue-600/40"
            : "bg-purple-900/40 border border-purple-700/40"
          }
        `}
      >
        {isUser ? (
          <User className="w-4 h-4 text-blue-400" />
        ) : (
          <Bot className="w-4 h-4 text-purple-400" />
        )}
      </div>

      {/* ── Bubble + Metadata Column ────────────────────────────────────── */}
      {/* max-w-[75%] prevents very long messages from spanning the full width,
          which would make them hard to read. */}
      <div className={`flex flex-col gap-1 max-w-[75%] ${isUser ? "items-end" : "items-start"}`}>
        {/* SAGE agent label for AI messages */}
        {!isUser && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#8B5CF6]/10 text-[#8B5CF6] border border-[#8B5CF6]/30 font-mono font-semibold mb-0.5">SAGE</span>
        )}

        {/* Main chat bubble — spec-exact styling */}
        <div
          className={`
            px-4 py-3 text-sm leading-relaxed
            ${isUser
              // User: solid dark blue — spec: bg-[#1E293B] text-slate-100 rounded-2xl rounded-tr-none
              ? "bg-[#1E293B] text-slate-100 rounded-2xl rounded-tr-none"
              // Assistant: gradient with border — spec: bg-gradient-to-r from-blue-950/20 to-purple-950/20
              //   border border-blue-800/40 rounded-2xl rounded-tl-none
              : "bg-gradient-to-r from-blue-950/20 to-purple-950/20 border border-blue-800/40 rounded-2xl rounded-tl-none text-slate-200"
            }
          `}
        >
          {isUser ? (
            // User messages are plain text — no markdown needed
            <span>{message.content}</span>
          ) : (
            // Assistant messages run through renderMarkdown for bold/italic/code
            <div className="space-y-0.5">
              {renderMarkdown(message.content)}
            </div>
          )}
        </div>

        {/* ── Citation Pills — RAG path only ───────────────────────────── */}
        {/* WHY check citations?.length > 0: the field is undefined for SQL/CHAT
            path messages, so we guard both the undefined and empty-array cases. */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1 mt-1">
            {message.citations.map((citation: any, idx: number) => (
              // idx suffix prevents key collision when the same invoice appears
              // twice in the citations array (e.g. two chunks from the same doc)
              <CitationPill key={`${citation.invoice_id}-${idx}`} citation={citation} />
            ))}
          </div>
        )}

        {/* ── SQL Audit Drawer — SQL path only ─────────────────────────── */}
        {/* WHY not show for user messages: generated_sql is always null on
            user-role messages; the guard keeps the JSX explicit. */}
        {!isUser && message.generated_sql && (
          <div className="w-full px-1">
            <SqlAuditDrawer sql={message.generated_sql} />
          </div>
        )}

        {/* Timestamp + feedback vote row */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-slate-500 px-1">{formattedTime}</span>
          {!isUser && <FeedbackVote messageId={message.id} initialVote={message.feedback} />}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// MessageStream — ordered list of bubbles with auto-scroll + typing indicator
// REASON: Separating the list renderer from the single-bubble renderer keeps
//   each component focused.  MessageStream handles the scroll side-effect;
//   MessageBubble handles the visual presentation.
// =============================================================================

interface MessageStreamProps {
  messages: ChatMessage[];
  isSending: boolean; // When true, shows the animated typing indicator
}

export function MessageStream({ messages, isSending }: MessageStreamProps) {
  // bottomRef is attached to an empty div at the end of the list.
  // scrollIntoView fires whenever messages or isSending changes, keeping
  // the latest content in view automatically (equivalent to WhatsApp behaviour).
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  return (
    <div className="flex flex-col gap-5 py-6 px-4">
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* ── Typing Indicator ────────────────────────────────────────────── */}
      {/* WHY three staggered bouncing dots: this is the universally recognised
          UX pattern for "the other party is typing".  It manages user
          expectations — they know a response is coming and won't re-send.
          animation-delay staggering is set via Tailwind's JIT arbitrary values. */}
      {isSending && (
        <div className="flex items-start gap-3">
          <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-purple-900/40 border border-purple-700/40">
            <Bot className="w-4 h-4 text-purple-400" />
          </div>
          <div className="px-4 py-3 bg-gradient-to-r from-blue-950/20 to-purple-950/20 border border-blue-800/40 rounded-2xl rounded-tl-none">
            <div className="flex gap-1 items-center h-4">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce [animation-delay:300ms]" />
            </div>
          </div>
        </div>
      )}

      {/* Scroll anchor — scrollIntoView targets this invisible element */}
      <div ref={bottomRef} />
    </div>
  );
}
