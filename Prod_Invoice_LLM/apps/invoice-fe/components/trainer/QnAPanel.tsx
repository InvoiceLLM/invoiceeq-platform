"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  Sliders,
  Send,
  Sparkles,
  Bot,
  User,
  CheckCircle2,
  AlertCircle,
  Wand2,
  Tag,
  Zap,
} from "lucide-react";
import { ChatMessage, ExtractedVariable } from "@/lib/trainer-service";

/**
 * Feature 6 Component: QnAPanel (Task 6.5 — Right Panel)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This component renders the right 50% split-panel column in the AI Trainer workspace.
 * Two core views are accessible via a top tab toggle:
 *
 *   Tab 1 — Chat Assistant:
 *     • Conversational message bubbles (User right-aligned, AI left-aligned).
 *     • AI "Thinking..." typing pulse animation during active processing.
 *     • Rule Candidate card inline within AI reply when a rule is created.
 *     • Quick-action suggestion chip strip for fast rule teaching.
 *     • Always-active text input bar at the bottom.
 *
 *   Tab 2 — Variables & Rules Inspector:
 *     • Active Rule Candidates list with emerald "Active" status badges.
 *     • Extracted Document Variables key-value grid with:
 *         – Emerald tick for corrected fields (updated by rule)
 *         – Amber warning for low-confidence fields (< 80%)
 *     • Click-to-highlight: selecting a variable triggers PDF bounding box.
 *
 * Design: Deep glassmorphism panel, message bubbles with gradient backgrounds,
 * animated suggestion chips, smooth tab indicator transition.
 */

interface QnAPanelProps {
  /** Array of chat messages in current sandbox session */
  chatHistory: ChatMessage[];
  /** Array of extracted variables from the loaded document */
  variables: ExtractedVariable[];
  /** Array of active rule strings registered during session */
  activeRules: string[];
  /** Callback fired when user submits a new chat rule / instruction */
  onSendMessage: (text: string) => void;
  /** Flag indicating active AI response is processing */
  isSending?: boolean;
  /** Callback fired when user clicks a variable row to highlight on PDF */
  onSelectVariable?: (variable: ExtractedVariable) => void;
  /** ID of currently selected variable */
  selectedVariableId?: string;
}

export default function QnAPanel({
  chatHistory,
  variables,
  activeRules,
  onSendMessage,
  isSending = false,
  onSelectVariable,
  selectedVariableId,
}: QnAPanelProps) {
  // Tab state: 'chat' or 'variables'
  const [activeTab, setActiveTab] = useState<"chat" | "variables">("chat");
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

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isSending) return;
    onSendMessage(inputText.trim());
    setInputText("");
  };

  const handleChipClick = (chipText: string) => {
    if (isSending) return;
    onSendMessage(chipText);
  };

  return (
    <div className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30">
      {/* ── Panel Top Tab Navigation ───────────────────────────────────── */}
      <div className="h-12 px-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between gap-3 shrink-0">
        {/* Tab Toggle Pill */}
        <div className="flex items-center gap-1 p-0.5 bg-[#111827]/80 rounded-xl border border-[#1E2D45]">
          {/* Chat tab */}
          <button
            type="button"
            onClick={() => setActiveTab("chat")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
              activeTab === "chat"
                ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Chat Assistant</span>
            <span className="ml-0.5 px-1.5 py-0.5 rounded-full bg-[#6366F1]/15 text-[#6366F1] border border-[#6366F1]/30 text-[10px] font-mono font-semibold leading-none">EVOLVE</span>
          </button>

          {/* Variables & Rules tab */}
          <button
            type="button"
            onClick={() => setActiveTab("variables")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
              activeTab === "variables"
                ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Variables & Rules</span>
            <span className="ml-0.5 px-1.5 py-0.5 rounded-full bg-white/15 text-[10px] font-mono leading-none">
              {variables.length}
            </span>
          </button>
        </div>

        {/* Active Rules counter badge — shown when rules exist */}
        {activeRules.length > 0 && (
          <div className="hidden sm:flex items-center gap-1.5 text-[11px] text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20 shrink-0">
            <Wand2 className="w-3 h-3 shrink-0" />
            <span>{activeRules.length} Rule{activeRules.length !== 1 ? "s" : ""} Active</span>
          </div>
        )}
      </div>

      {/* ════════════════════════════════════════════════════════════════
          TAB 1: Chat Assistant
      ════════════════════════════════════════════════════════════════ */}
      {activeTab === "chat" && (
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
                disabled={isSending}
                className="shrink-0 text-[11px] bg-[#111827] hover:bg-[#1E293B] text-slate-300 hover:text-white px-3 py-1 rounded-full border border-[#1E2D45] hover:border-blue-500/40 transition-all cursor-pointer disabled:opacity-40"
              >
                + {chip}
              </button>
            ))}
          </div>

          {/* ── Chat Input Form Bar ─────────────────────────────────── */}
          <form
            onSubmit={handleSend}
            className="p-3 bg-[#070D1A] border-t border-[#1E2D45] flex items-center gap-2 shrink-0"
          >
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Teach a rule (e.g. 'Read invoice date in DD/MM/YYYY format')…"
              disabled={isSending}
              className="flex-1 bg-[#111827] border border-[#1E2D45] text-white text-xs rounded-xl px-4 py-2.5 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/15 placeholder:text-slate-500 transition-colors"
            />
            <button
              type="submit"
              disabled={!inputText.trim() || isSending}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white p-2.5 rounded-xl transition-all shadow-md shadow-blue-600/20 shrink-0 cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          TAB 2: Extracted Variables & Active Rules Inspector
      ════════════════════════════════════════════════════════════════ */}
      {activeTab === "variables" && (
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* ── Section A: Active Rule Template Candidates ─────────── */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-300 flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
              <span>Active Rule Candidates ({activeRules.length})</span>
            </h4>

            {activeRules.length === 0 ? (
              <div className="p-4 bg-[#0B1120]/80 border border-dashed border-[#1E2D45] rounded-2xl text-xs text-slate-500 text-center leading-relaxed">
                No rules trained in this session yet.
                <br />
                Chat on the left to generate rule candidates.
              </div>
            ) : (
              <div className="space-y-1.5">
                {activeRules.map((rule, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-[#0B1120]/80 border border-emerald-500/20 rounded-xl flex items-center justify-between gap-2 text-xs text-emerald-300 hover:border-emerald-500/40 transition-colors"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Tag className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span className="font-mono text-[11px] truncate">{rule}</span>
                    </div>
                    <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                      Active
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Section B: Extracted Variables Key-Value Inspector ──── */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span>Extracted Variables ({variables.length})</span>
              <span className="text-[10px] text-slate-500 font-normal">Click to highlight in viewer</span>
            </h4>

            {variables.length === 0 ? (
              <div className="p-4 bg-[#0B1120]/80 border border-dashed border-[#1E2D45] rounded-2xl text-xs text-slate-500 text-center leading-relaxed">
                No extracted variables available.
                <br />
                <span className="text-[10px] text-slate-600 mt-1 block">
                  Variables populate dynamically once a grounding PDF is uploaded or a vendor seed is loaded.
                </span>
              </div>
            ) : (
              <div className="divide-y divide-[#1E2D45] border border-[#1E2D45] rounded-2xl overflow-hidden bg-[#0B1120]/80">
                {variables.map((v) => {
                  const isSelected = selectedVariableId === v.id;
                  return (
                    <div
                      key={v.id}
                      onClick={() => onSelectVariable && onSelectVariable(v)}
                      className={`p-3 flex items-center justify-between gap-3 text-xs transition-all cursor-pointer ${
                        isSelected
                          ? "bg-blue-500/10 border-l-4 border-l-blue-500"
                          : "hover:bg-[#111827]/60"
                      }`}
                    >
                      {/* Variable key + label */}
                      <div className="min-w-0">
                        <span className="text-[9px] text-slate-500 block uppercase tracking-wider font-mono mb-0.5">
                          {v.key}
                        </span>
                        <span className="font-medium text-white text-xs truncate block">{v.label}</span>
                      </div>

                      {/* Value chip + status icon */}
                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`font-mono text-xs px-2.5 py-1 rounded-lg font-semibold ${
                            v.isCorrected
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : "bg-[#111827] text-slate-200 border border-[#1E2D45]"
                          }`}
                        >
                          {v.value}
                        </span>

                        {/* Status icon: green check (corrected) or amber warning (low confidence) */}
                        {v.isCorrected ? (
                          <span title="Updated by Rule">
                            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          </span>
                        ) : v.confidence < 0.8 ? (
                          <span title={`Low Confidence (${Math.round(v.confidence * 100)}%)`}>
                            <AlertCircle className="w-4 h-4 text-amber-400" />
                          </span>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
