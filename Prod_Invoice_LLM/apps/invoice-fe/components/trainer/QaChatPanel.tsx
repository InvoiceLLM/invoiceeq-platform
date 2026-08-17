"use client";

import React, { useEffect, useRef, useState } from "react";
import { MessageSquare, Send, Bot, User, ThumbsDown, Info, Lock } from "lucide-react";
import { ChatMessage } from "@/lib/trainer-service";
import ThumbsDownTriage from "@/components/chat/ThumbsDownTriage";

/**
 * Feature 14 Component: QaChatPanel
 *
 * FOR MANAGERS & DEVELOPERS:
 * A place to *ask questions about* the invoice that's loaded — "what did we
 * charge for freight on this one?", "how does this compare to their last
 * three?" — running the real query agent against real tenant data.
 *
 * WHY IT IS VISUALLY AND STRUCTURALLY SEPARATE FROM RULE CREATION:
 * the flow this redesign replaced had exactly one text box, and that box both
 * answered questions and silently created extraction rules. That ambiguity is
 * the root of the problem Feature 18 was opened about — a user asking a question
 * could teach the extractor something, with no checkpoint in between. So this
 * panel states plainly, in the UI and not just in a doc, that **nothing typed
 * here can create an extraction rule**. Its only training effect is indirect:
 * a thumbs-down on an answer opens the chat-correction lane, which produces a
 * chat-behaviour rule and provably never touches
 * `ExtractionTemplate.rules["constraints"]`.
 *
 * Thumbs-down works here for a concrete backend reason: QA turns are now real
 * `ChatMessage` rows (they used to live only in a Redis scratch dict with
 * synthetic `msg-xxxxxxxx` ids, so there was nothing to attach feedback to).
 * `sendChatMessage` returns the real assistant message id, and only messages
 * carrying one get a vote control — a synthetic id would 404 the feedback API.
 */

interface QaChatPanelProps {
  chatHistory: ChatMessage[];
  onSendMessage: (text: string) => void;
  isSending?: boolean;
  /** Why the panel can't be used yet, or null when it can. */
  disabledReason?: string | null;
  /** Whether this user may commit a chat rule from a thumbs-down. */
  canTrain: boolean;
  vendorName?: string;
}

/** A real `ChatMessage` UUID, as opposed to the session's synthetic `msg-xxxx`. */
function isRealMessageId(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

export default function QaChatPanel({
  chatHistory,
  onSendMessage,
  isSending = false,
  disabledReason = null,
  canTrain,
  vendorName,
}: QaChatPanelProps) {
  const [inputText, setInputText] = useState("");
  const [triageMessageId, setTriageMessageId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isSending]);

  const isDisabled = isSending || disabledReason !== null;

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isDisabled) return;
    onSendMessage(inputText.trim());
    setInputText("");
  };

  return (
    <div
      data-testid="trainer-qa-panel"
      className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30"
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="h-12 px-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center gap-2 shrink-0">
        <MessageSquare className="w-4 h-4 text-blue-400 shrink-0" />
        <h2 className="text-xs font-semibold text-white truncate">Ask about this invoice</h2>
        <span className="px-1.5 py-0.5 rounded-full bg-[#6366F1]/15 text-[#6366F1] border border-[#6366F1]/30 text-[10px] font-mono font-semibold leading-none shrink-0">
          SAGE
        </span>
      </div>

      {/* The separation, stated in the UI rather than only in a doc. */}
      <div className="px-3 py-2 bg-blue-500/5 border-b border-blue-500/20 flex items-start gap-2 shrink-0">
        <Info className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
        <p className="text-[10px] text-blue-200/80 leading-relaxed">
          Questions only — nothing here creates an extraction rule. To change how this
          invoice is read, correct an alert in the panel beside this one. If an{" "}
          <span className="font-semibold">answer</span> is wrong, use the thumbs-down on it.
        </p>
      </div>

      {/* ── Conversation ────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {chatHistory.length === 0 && !isSending && (
          <div className="flex flex-col items-center justify-center h-full min-h-[160px] text-center gap-3 py-10">
            <div className="w-11 h-11 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <MessageSquare className="w-5 h-5" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-300">Ask a question</p>
              <p className="text-xs text-slate-500 mt-1 max-w-xs leading-relaxed">
                {vendorName
                  ? `Anything about ${vendorName}'s invoices — this one or their history.`
                  : "Anything about this invoice or this vendor's history."}
              </p>
            </div>
          </div>
        )}

        {chatHistory.map((msg) => {
          const isUser = msg.sender === "user";
          const votable = !isUser && isRealMessageId(msg.id);
          return (
            <div
              key={msg.id}
              className={`flex items-end gap-2.5 ${isUser ? "flex-row-reverse" : "flex-row"}`}
            >
              <div
                className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 shadow-md ${
                  isUser
                    ? "bg-blue-600 text-white"
                    : "bg-[#111827] text-emerald-400 border border-emerald-500/25"
                }`}
              >
                {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              <div
                className={`max-w-[80%] text-xs leading-relaxed shadow-lg ${
                  isUser
                    ? "bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-2xl rounded-br-sm px-4 py-3 font-medium"
                    : "bg-[#111827] text-slate-200 border border-[#1E2D45] rounded-2xl rounded-bl-sm px-4 py-3"
                }`}
              >
                <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span
                    className={`text-[10px] font-mono ${
                      isUser ? "text-blue-200/60" : "text-slate-500"
                    }`}
                  >
                    {msg.timestamp}
                  </span>
                  {votable && (
                    <button
                      type="button"
                      data-testid="qa-thumbs-down"
                      title="This answer was wrong"
                      onClick={() => setTriageMessageId(msg.id)}
                      className="ml-auto p-1 rounded text-slate-600 hover:text-rose-400 transition-colors cursor-pointer"
                    >
                      <ThumbsDown className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {isSending && (
          <div className="flex items-end gap-2.5">
            <div className="w-7 h-7 rounded-xl bg-[#111827] text-emerald-400 border border-emerald-500/25 flex items-center justify-center shadow-md">
              <Bot className="w-4 h-4" />
            </div>
            <div className="bg-[#111827] border border-[#1E2D45] px-4 py-3 rounded-2xl rounded-bl-sm">
              <div className="flex gap-1 items-center h-4">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    style={{ animationDelay: `${delay}ms` }}
                    className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {toast && (
        <div className="px-3 py-2 bg-emerald-500/10 border-t border-emerald-500/25 text-[10px] text-emerald-300 shrink-0">
          {toast}
        </div>
      )}

      {/* ── Input ───────────────────────────────────────────────────────── */}
      <form
        onSubmit={handleSend}
        className="p-3 bg-[#070D1A] border-t border-[#1E2D45] flex flex-col gap-2 shrink-0"
      >
        {disabledReason && (
          <div className="flex items-start gap-2 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/25 rounded-lg px-3 py-2">
            <Lock className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{disabledReason}</span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder={disabledReason || "Ask about this invoice or this vendor…"}
            title={disabledReason || undefined}
            disabled={isDisabled}
            data-testid="qa-input"
            className="flex-1 bg-[#111827] border border-[#1E2D45] text-white text-xs rounded-xl px-4 py-2.5 focus:outline-none focus:border-blue-500/60 placeholder:text-slate-500 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          />
          <button
            type="submit"
            disabled={!inputText.trim() || isDisabled}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white p-2.5 rounded-xl transition-all shadow-md shrink-0 cursor-pointer"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </form>

      {/* Same triage flow the main Chat screen uses — one implementation, so the
          two surfaces can't drift apart. */}
      <ThumbsDownTriage
        isOpen={triageMessageId !== null}
        messageId={triageMessageId || ""}
        canTrain={canTrain}
        onClose={() => setTriageMessageId(null)}
        onResolved={(summary) => {
          setToast(summary);
          setTimeout(() => setToast(null), 6000);
        }}
      />
    </div>
  );
}
