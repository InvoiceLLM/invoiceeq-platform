"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  Send,
  Sparkles,
  Bot,
  User,
  Zap,
  Lock,
} from "lucide-react";
import { ChatMessage } from "@/lib/trainer-service";

/**
 * Feature 6 Component: QnAPanel (Task 6.5 — Chat panel)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders the conversational panel in the AI Trainer workspace:
 *     • Conversational message bubbles (User right-aligned, AI left-aligned).
 *     • AI "Thinking..." typing pulse animation during active processing.
 *     • Rule Candidate card inline within AI reply when a rule is created.
 *     • Quick-action suggestion chip strip for fast rule teaching.
 *     • Always-active text input bar at the bottom.
 *
 * FE Gap 111: this used to be a two-tab panel — Chat, plus a "Variables &
 * Rules" inspector holding the extracted field list and the active rule
 * candidates. Both of those now have dedicated always-visible homes
 * (`ExtractedFieldsPanel` and `RulesRail`), so the tab strip is gone and this
 * panel does one thing. That tab was a real cost, not just clutter: reading
 * the field values you were correcting meant hiding the chat you were
 * correcting them in, which is the workflow the whole screen exists for.
 *
 * Design: Deep glassmorphism panel, message bubbles with gradient backgrounds,
 * animated suggestion chips.
 */

interface QnAPanelProps {
  /** Array of chat messages in current sandbox session */
  chatHistory: ChatMessage[];
  /** Callback fired when user submits a new chat rule / instruction */
  onSendMessage: (text: string) => void;
  /** Flag indicating active AI response is processing */
  isSending?: boolean;
  /**
   * FE Gap 171: why the chat cannot be used yet (no active session), or null
   * when it can. The panel used to have no awareness of this at all: it took
   * the text, cleared the input as if it had been sent, and the page's
   * `handleSendMessage` dropped it on a silent early return. When set, the
   * input and the suggestion chips are disabled and the reason is shown, so
   * nothing typed can be lost.
   */
  disabledReason?: string | null;
}

export default function QnAPanel({
  chatHistory,
  onSendMessage,
  isSending = false,
  disabledReason = null,
}: QnAPanelProps) {
  const [inputText, setInputText] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  // ── Estimated progress during a chat correction ────────────────────────
  // A correction round-trip is a single synchronous backend call covering two
  // real LLM steps (refine constraints, then re-extract with them) — the
  // backend doesn't stream incremental progress, so this is a client-side
  // elapsed-time estimate against a typical ~28s round-trip, not a real
  // server-reported percentage. It's capped short of 100% and jumps there
  // only once the actual response lands (isSending flips false), so it never
  // falsely claims completion before the real answer arrives.
  const [progressPct, setProgressPct] = useState(0);
  const ESTIMATED_DURATION_MS = 28000;
  useEffect(() => {
    if (!isSending) {
      setProgressPct(0);
      return;
    }
    const startedAt = Date.now();
    const interval = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      // Approach 92% asymptotically so it never appears finished while still waiting.
      const pct = Math.min(92, Math.round((elapsed / ESTIMATED_DURATION_MS) * 92));
      setProgressPct(pct);
    }, 300);
    return () => clearInterval(interval);
  }, [isSending]);

  const progressStage =
    progressPct < 35 ? "Analyzing correction..." :
    progressPct < 75 ? "Re-extracting with updated rules..." :
    "Finalizing...";

  // Quick-action suggestion chips for common rule patterns
  const suggestionChips = [
    "Dates are in DD/MM/YYYY format",
    "VAT tax is 18% applied after line discount",
    "Match invoice number prefix INV-",
    "Treat Freight charges as a separate line item",
  ];

  // Auto-scroll chat container on new message or typing indicator
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isSending]);

  const isDisabled = isSending || disabledReason !== null;

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    // Gap 171: the typed text is only cleared once it has actually been handed
    // over. With no session the input is disabled anyway, but the guard is kept
    // here too so the field can never be emptied by a submit that goes nowhere.
    if (!inputText.trim() || isDisabled) return;
    onSendMessage(inputText.trim());
    setInputText("");
  };

  const handleChipClick = (chipText: string) => {
    if (isDisabled) return;
    onSendMessage(chipText);
  };

  return (
    <div className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30">
      {/* ── Panel header ───────────────────────────────────────────────── */}
      {/* Gap 111: a plain title, not a tab strip. The panel has one job now. */}
      <div className="h-12 px-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center gap-2 shrink-0">
        <MessageSquare className="w-4 h-4 text-blue-400 shrink-0" />
        <h2 className="text-xs font-semibold text-white truncate">Chat Assistant</h2>
        <span className="px-1.5 py-0.5 rounded-full bg-[#6366F1]/15 text-[#6366F1] border border-[#6366F1]/30 text-[10px] font-mono font-semibold leading-none shrink-0">
          EVOLVE
        </span>
        <span className="hidden lg:inline text-[10px] text-slate-500 truncate ml-1">
          Describe a correction in plain language — it becomes a rule candidate
        </span>
      </div>

      {/* ── Conversation ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-h-0">
          {/* Scrollable Chat Message History */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Empty chat state */}
            {chatHistory.length === 0 && !isSending && (
              <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-center gap-3 py-12">
                <div className="w-12 h-12 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shadow-md shadow-blue-500/10">
                  <Zap className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-300">Start teaching a rule</p>
                  <p className="text-xs text-slate-500 mt-1">
                    Type an instruction or click a suggestion chip below.
                  </p>
                </div>
              </div>
            )}

            {/* Message bubbles */}
            {chatHistory.map((msg) => {
              const isUser = msg.sender === "user";
              return (
                <div
                  key={msg.id}
                  className={`flex items-end gap-2.5 ${isUser ? "flex-row-reverse" : "flex-row"}`}
                >
                  {/* Avatar bubble */}
                  <div
                    className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 shadow-md ${
                      isUser
                        ? "bg-blue-600 text-white"
                        : "bg-[#111827] text-emerald-400 border border-emerald-500/25"
                    }`}
                  >
                    {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                  </div>

                  {/* Message content bubble */}
                  <div
                    className={`max-w-[80%] text-xs leading-relaxed shadow-lg ${
                      isUser
                        ? /* User: blue gradient right-aligned bubble */
                          "bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-2xl rounded-br-sm px-4 py-3 font-medium"
                        : /* AI: glass dark left-aligned bubble */
                          "bg-[#111827] text-slate-200 border border-[#1E2D45] rounded-2xl rounded-bl-sm px-4 py-3"
                    }`}
                  >
                    <p className="leading-relaxed">{msg.text}</p>

                    {/* Inline Rule Candidate card — shown in AI replies when a rule was generated */}
                    {msg.suggestedRule && (
                      <div className="mt-3 pt-2.5 border-t border-white/10 flex items-start gap-2 text-[11px] bg-emerald-500/10 p-2.5 rounded-xl border border-emerald-500/20">
                        <Sparkles className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-semibold block text-emerald-400 mb-0.5">
                            Rule Candidate Created:
                          </span>
                          <span className="font-mono text-[10px] text-emerald-200">
                            &ldquo;{msg.suggestedRule}&rdquo;
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Timestamp */}
                    <span
                      className={`block mt-2 text-[10px] font-mono text-right ${
                        isUser ? "text-blue-200/60" : "text-slate-500"
                      }`}
                    >
                      {msg.timestamp}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* AI Thinking / Typing Pulse Indicator, with an estimated progress bar.
                A correction re-runs extraction (2 real LLM calls), typically ~25-30s —
                the bar/percentage is a client-side elapsed-time estimate (see the
                progressPct effect above), not a real backend-reported value. */}
            {isSending && (
              <div className="flex items-end gap-2.5">
                <div className="w-7 h-7 rounded-xl bg-[#111827] text-emerald-400 border border-emerald-500/25 flex items-center justify-center shadow-md">
                  <Bot className="w-4 h-4" />
                </div>
                <div className="bg-[#111827] border border-[#1E2D45] px-4 py-3 rounded-2xl rounded-bl-sm min-w-[220px]">
                  <div className="flex items-center gap-1.5">
                    {[0, 150, 300].map((delay) => (
                      <span
                        key={delay}
                        style={{ animationDelay: `${delay}ms` }}
                        className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
                      />
                    ))}
                    <span className="ml-2 text-[11px] text-slate-400">{progressStage}</span>
                    <span className="ml-auto text-[10px] font-mono text-blue-400">{progressPct}%</span>
                  </div>
                  <div className="mt-2 h-1 bg-[#1E2D45] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 transition-all duration-300 ease-out rounded-full"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Scroll anchor */}
            <div ref={chatEndRef} />
          </div>

          {/* ── Quick Suggestion Chips Bar ──────────────────────────── */}
          <div className="px-3 py-2 bg-[#0B1120]/90 border-t border-[#1E2D45] overflow-x-auto no-scrollbar flex items-center gap-2 shrink-0">
            <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wide shrink-0">
              Try:
            </span>
            {suggestionChips.map((chip, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => handleChipClick(chip)}
                disabled={isDisabled}
                title={disabledReason || chip}
                className="shrink-0 text-[11px] bg-[#111827] hover:bg-[#1E293B] text-slate-300 hover:text-white px-3 py-1 rounded-full border border-[#1E2D45] hover:border-blue-500/40 transition-all cursor-pointer disabled:opacity-40"
              >
                + {chip}
              </button>
            ))}
          </div>

          {/* ── Chat Input Form Bar ─────────────────────────────────── */}
          <form
            onSubmit={handleSend}
            className="p-3 bg-[#070D1A] border-t border-[#1E2D45] flex flex-col gap-2 shrink-0"
          >
            {/* Gap 171: the blocker is stated above the input, in the same
                amber "not ready yet" treatment the Trainer uses elsewhere,
                rather than being left for the user to infer from a dead field. */}
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
              placeholder={
                disabledReason || "Teach a rule (e.g. 'Read invoice date in DD/MM/YYYY format')…"
              }
              title={disabledReason || undefined}
              disabled={isDisabled}
              className="flex-1 bg-[#111827] border border-[#1E2D45] text-white text-xs rounded-xl px-4 py-2.5 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/15 placeholder:text-slate-500 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            />
            <button
              type="submit"
              title={disabledReason || "Send"}
              disabled={!inputText.trim() || isDisabled}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white p-2.5 rounded-xl transition-all shadow-md shadow-blue-600/20 shrink-0 cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
            </div>
          </form>
      </div>
    </div>
  );
}
