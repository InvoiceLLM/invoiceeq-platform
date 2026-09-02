// =============================================================================
// FILE: components/chat/MessageBubble.tsx
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: Each message in the chat thread needs to be rendered with
//   role-specific styling, markdown formatting, and optional sub-components
//   (citation pills, SQL drawer).  This file exports two components:
//     MessageBubble — renders a single ChatMessage
//     MessageStream — renders the full ordered list with auto-scroll and a
//                     typing indicator while the backend is processing
//   MARKDOWN RENDERING (Gap 229, FE): previously a hand-rolled regex renderer
//   covering only **bold**/*italic*/`code`, on the reasoning that adding
//   react-markdown needed Next.js transpilePackages config. That reasoning
//   didn't hold up: react-markdown is plain ESM/CJS-dual and works in a
//   "use client" component on Next 14.2.3 with no extra config. Meanwhile the
//   backend was already emitting real GFM markdown the old renderer mangled
//   into literal text — SQL-route replies append a real pipe table
//   (`### Query Results` + `|`-delimited rows), RAG-route replies append real
//   markdown links (`[Source: ...](file:///...)`) — so users were seeing raw
//   `###`/`|`/`[...](...)` syntax, not just "plain-feeling" prose. Swapped to
//   `react-markdown` + `remark-gfm` (tables/strikethrough), with `components`
//   overrides below to keep the existing dark-theme styling instead of
//   react-markdown's unstyled defaults.
// =============================================================================

"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, User, ThumbsUp, ThumbsDown, Loader2, Sparkles, AlertCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
// markdownComponents — style overrides for react-markdown (Gap 229)
// WHY: react-markdown renders plain, unstyled HTML elements by default; these
// overrides keep the same palette the old regex renderer used for bold/code
// (white/semibold; dark bg + green mono text matching SqlAuditDrawer) and add
// matching dark-theme styles for the elements that are now newly renderable
// (lists, tables, headings, links, code blocks, blockquotes) instead of
// leaving them to browser defaults, which would look out of place in the
// bubble.
// =============================================================================
const markdownComponents = {
  strong: (props: any) => <strong className="text-white font-semibold" {...props} />,
  em: (props: any) => <em className="text-slate-300 italic" {...props} />,
  code: ({ inline, className, children, ...props }: any) =>
    inline ? (
      <code
        className="bg-[#0B0F19] text-[#10B981] px-1.5 py-0.5 rounded text-[11px] font-mono border border-[#222D3D]"
        {...props}
      >
        {children}
      </code>
    ) : (
      <code className="block bg-[#0B0F19] text-[#10B981] p-2 rounded-lg text-[11px] font-mono border border-[#222D3D] overflow-x-auto" {...props}>
        {children}
      </code>
    ),
  pre: (props: any) => <pre className="my-2 max-w-full" {...props} />,
  p: (props: any) => <p className="mb-1 last:mb-0" {...props} />,
  ul: (props: any) => <ul className="list-disc list-outside ml-4 my-1 space-y-0.5" {...props} />,
  ol: (props: any) => <ol className="list-decimal list-outside ml-4 my-1 space-y-0.5" {...props} />,
  li: (props: any) => <li className="text-slate-200" {...props} />,
  h1: (props: any) => <h1 className="text-sm font-bold text-white mt-2 mb-1" {...props} />,
  h2: (props: any) => <h2 className="text-sm font-bold text-white mt-2 mb-1" {...props} />,
  h3: (props: any) => <h3 className="text-xs font-bold text-white uppercase tracking-wide mt-2 mb-1" {...props} />,
  a: (props: any) => {
    const href = props.href || "";
    const isInternal = href.startsWith("/") || href.startsWith("#");
    if (isInternal) {
      return (
        <a
          className="text-[#3B82F6] hover:text-[#60A5FA] underline underline-offset-2 cursor-pointer font-medium"
          {...props}
        />
      );
    }
    return (
      <a
        className="text-[#3B82F6] hover:text-[#60A5FA] underline underline-offset-2 font-medium"
        target="_blank"
        rel="noopener noreferrer"
        {...props}
      />
    );
  },
  blockquote: (props: any) => (
    <blockquote className="border-l-2 border-[#3B82F6]/40 pl-2 my-1 text-slate-400 italic" {...props} />
  ),
  table: (props: any) => (
    <div className="overflow-x-auto my-2">
      <table className="min-w-full text-xs border-collapse" {...props} />
    </div>
  ),
  thead: (props: any) => <thead className="border-b border-[#222D3D]" {...props} />,
  th: (props: any) => <th className="text-left font-semibold text-white px-2 py-1" {...props} />,
  td: (props: any) => <td className="px-2 py-1 border-t border-[#222D3D]/60 text-slate-200" {...props} />,
};

function renderMarkdown(text: string): React.ReactNode {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {text}
    </ReactMarkdown>
  );
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
              : message.status === "failed"
              ? "bg-red-950/30 border border-red-800/50 rounded-2xl rounded-tl-none text-red-200"
              : message.status === "queued" || message.status === "processing"
              ? "bg-gradient-to-r from-blue-950/30 via-indigo-950/30 to-purple-950/30 border border-purple-600/40 rounded-2xl rounded-tl-none text-slate-200 shadow-[0_0_15px_rgba(139,92,246,0.15)]"
              : "bg-gradient-to-r from-blue-950/20 to-purple-950/20 border border-blue-800/40 rounded-2xl rounded-tl-none text-slate-200"
            }
          `}
        >
          {isUser ? (
            // User messages are plain text — no markdown needed
            <span>{message.content}</span>
          ) : message.status === "failed" ? (
            <div className="flex items-start gap-2 text-red-300">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />
              <div className="space-y-1">
                <p className="font-medium text-xs text-red-200">Query Failed</p>
                <p className="text-xs text-red-300/80">
                  {message.error_message || message.content || "Something went wrong while processing your request."}
                </p>
              </div>
            </div>
          ) : message.status === "queued" || message.status === "processing" ? (
            <div className="flex flex-col gap-2 py-0.5">
              <div className="flex items-center gap-2 text-purple-300">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-purple-400" />
                <span className="text-xs font-medium tracking-wide">
                  {message.error_message || (message.status === "queued" ? "Queued in line (Slot reserved)..." : "Analyzing query and documents...")}
                </span>
              </div>
              <div className="flex items-center gap-1.5 pl-5">
                <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse [animation-delay:200ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse [animation-delay:400ms]" />
              </div>
            </div>
          ) : (
            // Assistant messages run through renderMarkdown (Gap 229: full GFM
            // markdown now — bold/italic/code plus lists/tables/headings/links)
            <div className="space-y-0.5">
              {renderMarkdown(message.content)}
            </div>
          )}
        </div>

        {/* ── Citation Pills — RAG path only ───────────────────────────── */}
        {/* WHY check citations?.length > 0: the field is undefined for SQL/CHAT
            path messages, so we guard both the undefined and empty-array cases. */}
        {!isUser && message.status === "completed" && message.citations && message.citations.length > 0 && (
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
        {!isUser && message.status === "completed" && message.generated_sql && (
          <div className="w-full px-1">
            <SqlAuditDrawer sql={message.generated_sql} />
          </div>
        )}

        {/* Timestamp + feedback vote row */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-slate-500 px-1">{formattedTime}</span>
          {!isUser && message.status === "completed" && (
            <FeedbackVote messageId={message.id} initialVote={message.feedback} />
          )}
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

  const showTypingIndicator =
    isSending &&
    (!messages.length || messages[messages.length - 1].role === "user");

  return (
    <div className="flex flex-col gap-5 py-6 px-4">
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* ── Typing Indicator ────────────────────────────────────────────── */}
      {showTypingIndicator && (
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
