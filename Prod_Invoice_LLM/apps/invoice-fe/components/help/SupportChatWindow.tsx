"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  Bot,
  User,
  Sparkles,
  Ticket,
  AlertTriangle,
  ArrowRight,
  HelpCircle,
  Shield,
  RotateCcw,
} from "lucide-react";
import { SupportTicketModal, type EscalationData } from "./SupportTicketModal";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** BE Gap 256: echoed topic id for anaphoric follow-up resolution. */
  topicId?: string | null;
  suggestEscalation?: boolean;
  /**
   * BE Gap 254: "no help article matched", which is not the same claim as
   * `suggestEscalation` ("a real incident was detected"). Kept as its own flag
   * so a plain miss renders a neutral affordance instead of the red incident
   * card — while still leaving a way to raise a ticket, which setting
   * `suggest_escalation=False` on the backend fallback would otherwise remove.
   */
  lowConfidence?: boolean;
  escalationContext?: {
    category?: string;
    priority?: "LOW" | "NORMAL" | "URGENT";
    subject?: string;
    errorCode?: string;
  } | null;
}

const PROMPT_CHIPS = [
  { label: "How do I train a new vendor format?", query: "How do I train a new vendor format?" },
  { label: "Why is an invoice flagged in Auditor?", query: "Why is an invoice flagged in Auditor?" },
  { label: "Setup inbound email forwarding", query: "How do I setup inbound email forwarding?" },
  { label: "Simulate ERP Batch Sync Timeout (504)", query: "We experienced a 504 gateway timeout during batch sync", isError: true },
];

const INTRO_MESSAGE: ChatMessage = {
  id: "intro-1",
  role: "assistant",
  content:
    "Hello! I am **SAGE**, your AI Support & Troubleshooting Assistant.\n\n" +
    "Ask me anything about platform workflows, training custom extraction rules, resolving auditor alerts, or system integrations. If we run into an unresolvable issue, I can automatically draft a priority support ticket for our engineering team.",
};

const STORAGE_KEY = "invoiceeq_support_chat_history";

export function SupportChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO_MESSAGE]);
  const [isClient, setIsClient] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalData, setModalData] = useState<EscalationData | null>(null);

  // Restore conversation history from sessionStorage on mount (FE Gap 250)
  useEffect(() => {
    setIsClient(true);
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setMessages(parsed);
        }
      }
    } catch {
      // sessionStorage unavailable or parse error; fallback to default
    }
  }, []);

  // Sync conversation history to sessionStorage on every message update (FE Gap 250)
  useEffect(() => {
    if (isClient) {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
      } catch {
        // sessionStorage write error
      }
    }
  }, [messages, isClient]);

  const handleClearChat = () => {
    setMessages([INTRO_MESSAGE]);
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSend = async (userQuery?: string) => {
    const text = (userQuery || input).trim();
    if (!text || loading) return;

    const userMessageId = `user-${Date.now()}`;
    const newMessages: ChatMessage[] = [
      ...messages,
      { id: userMessageId, role: "user", content: text },
    ];
    setMessages(newMessages);
    if (!userQuery) setInput("");
    setLoading(true);

    try {
      const historyPayload = newMessages.map((m) => ({
        role: m.role,
        content: typeof m.content === "string" ? m.content : "",
      }));

      const lastTopicId = [...newMessages]
        .reverse()
        .find((m) => m.role === "assistant" && m.topicId)?.topicId ?? null;

      const res = await fetch("/api/support/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: historyPayload,
          last_topic_id: lastTopicId,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || `Support request failed (${res.status})`);
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `bot-${Date.now()}`,
          role: "assistant",
          content: data.answer || "I received your request.",
          topicId: data.topic_id ?? null,
          suggestEscalation: !!data.suggest_escalation,
          lowConfidence: !!data.low_confidence,
          escalationContext: data.escalation_context,
        },
      ]);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        {
          id: `bot-err-${Date.now()}`,
          role: "assistant",
          content:
            "I encountered a temporary connection issue communicating with the troubleshooting service. " +
            "You can use the **Raise Support Ticket** button to dispatch your inquiry directly.",
          suggestEscalation: true,
          escalationContext: {
            category: "TECHNICAL_SUPPORT",
            priority: "URGENT",
            subject: `Troubleshooting connection error: ${text.slice(0, 50)}`,
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenEscalation = (msg: ChatMessage) => {
    const transcript = messages.map((m) => ({
      role: m.role,
      content: typeof m.content === "string" ? m.content : "",
    }));

    setModalData({
      category: msg.escalationContext?.category || "TECHNICAL_SUPPORT",
      priority: msg.escalationContext?.priority || "NORMAL",
      subject: msg.escalationContext?.subject || "Technical Assistance Request",
      errorCode: msg.escalationContext?.errorCode,
      transcript,
    });
    setModalOpen(true);
  };

  const handleOpenDirectTicket = () => {
    setModalData(null);
    setModalOpen(true);
  };

  return (
    <>
      <div id="support-chat-window" className="flex flex-col h-[700px] bg-[#111722] border border-[#222D3D] rounded-2xl overflow-hidden shadow-2xl">
        {/* Chat Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#222D3D] bg-[#151B26]/80 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-cyan-500 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-white">SAGE Support Assistant</span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-[#10B981] text-[10px] font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse" />
                  Live Platform Agent
                </span>
              </div>
              <p className="text-[11px] text-slate-400">
                Interactive platform troubleshooting &amp; direct escalation bridge
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {messages.length > 1 && (
              <button
                id="clear-chat-history-btn"
                type="button"
                onClick={handleClearChat}
                title="Clear conversation history"
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#1E293B] hover:bg-[#2A374A] border border-[#222D3D] text-slate-400 hover:text-slate-200 text-xs font-medium transition-all active:scale-95"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Clear Chat</span>
              </button>
            )}

            {/* Single Dedicated Direct Ticket Button in Chat Header */}
            <button
              id="direct-raise-ticket-btn"
              type="button"
              onClick={handleOpenDirectTicket}
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-gradient-to-r from-blue-600/20 to-cyan-500/20 hover:from-blue-600/30 hover:to-cyan-500/30 border border-cyan-500/40 text-cyan-300 text-xs font-semibold transition-all hover:shadow-lg hover:shadow-cyan-500/10 active:scale-95"
            >
              <Ticket className="w-3.5 h-3.5 text-cyan-400" />
              <span>Raise Ticket Directly</span>
            </button>
          </div>
        </div>

        {/* Message Stream */}
        <div id="support-chat-messages" className="flex-1 p-6 overflow-y-auto space-y-6">
          {messages.map((m) => {
            const isUser = m.role === "user";
            return (
              <div
                key={m.id}
                className={`flex gap-3.5 max-w-3xl ${isUser ? "ml-auto flex-row-reverse" : ""}`}
              >
                {/* Avatar */}
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
                    isUser
                      ? "bg-blue-600 text-white"
                      : "bg-[#1E293B] border border-[#222D3D] text-cyan-400"
                  }`}
                >
                  {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                </div>

                {/* Bubble */}
                <div
                  className={`rounded-2xl p-4 text-xs sm:text-sm leading-relaxed space-y-3 ${
                    isUser
                      ? "bg-blue-600 text-white rounded-tr-none shadow-md shadow-blue-600/20"
                      : "bg-[#151B26] border border-[#222D3D] text-slate-200 rounded-tl-none"
                  }`}
                >
                  <div className="whitespace-pre-wrap font-sans">
                    {typeof m.content === "string" ? m.content : ""}
                  </div>

                  {/* Inline Escalation Card */}
                  {!isUser && m.suggestEscalation && (
                    <div
                      id="smart-escalation-card"
                      className="mt-3 p-3.5 rounded-xl bg-gradient-to-br from-rose-950/40 to-slate-900/60 border border-rose-500/40 space-y-2.5 animate-in fade-in slide-in-from-bottom-2 duration-300"
                    >
                      <div className="flex items-center gap-2 text-rose-300 font-semibold text-xs">
                        <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                        <span>Issue Diagnosis &amp; Recommended Escalation</span>
                      </div>
                      <p className="text-[11.5px] text-slate-300">
                        This issue can be forwarded directly to engineering with your full diagnostic context pre-filled.
                      </p>
                      <button
                        id="escalate-ticket-btn"
                        onClick={() => handleOpenEscalation(m)}
                        className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-rose-600 to-rose-700 hover:from-rose-500 hover:to-rose-600 text-white text-xs font-bold rounded-lg shadow-md shadow-rose-600/30 transition-all hover:scale-[1.01] active:scale-[0.99]"
                      >
                        <Ticket className="w-3.5 h-3.5" />
                        <span>Raise Support Ticket from this Issue</span>
                        <ArrowRight className="w-3 h-3 ml-1 opacity-70" />
                      </button>
                    </div>
                  )}

                  {/* Neutral low-confidence card (BE Gap 254). Deliberately not
                      the escalation card: no red framing, no "Issue Diagnosis"
                      wording, nothing implying an incident was detected — just
                      the ticket affordance an unanswered question still needs. */}
                  {!isUser && !m.suggestEscalation && m.lowConfidence && (
                    <div
                      id="low-confidence-card"
                      className="mt-3 p-3.5 rounded-xl bg-[#0F1629]/70 border border-[#222D3D] space-y-2.5"
                    >
                      <div className="flex items-center gap-2 text-slate-300 font-semibold text-xs">
                        <HelpCircle className="w-4 h-4 text-slate-400 shrink-0" />
                        <span>Didn&apos;t find an answer?</span>
                      </div>
                      <p className="text-[11.5px] text-slate-400">
                        Our support team can pick this up directly — your question will be included.
                      </p>
                      <button
                        id="low-confidence-ticket-btn"
                        onClick={() => handleOpenEscalation(m)}
                        className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#1E293B] hover:bg-[#26364d] border border-[#2E3D52] text-slate-200 text-xs font-semibold rounded-lg transition-all active:scale-[0.99]"
                      >
                        <Ticket className="w-3.5 h-3.5 text-slate-400" />
                        <span>Raise a Ticket</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="flex gap-3.5 max-w-lg">
              <div className="w-8 h-8 rounded-lg bg-[#1E293B] border border-[#222D3D] flex items-center justify-center text-cyan-400 shrink-0">
                <Bot className="w-4 h-4" />
              </div>
              <div className="rounded-2xl rounded-tl-none p-4 bg-[#151B26] border border-[#222D3D] text-slate-400 text-xs flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-bounce" />
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-bounce [animation-delay:0.2s]" />
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-bounce [animation-delay:0.4s]" />
                <span className="ml-1 text-[11px] text-slate-500 font-mono">Analyzing documentation...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Prompt Chips */}
        <div className="px-6 py-2.5 bg-[#0F1629]/60 border-t border-[#222D3D] flex items-center gap-2 overflow-x-auto no-scrollbar">
          <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold shrink-0 flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-cyan-400" />
            Quick:
          </span>
          {PROMPT_CHIPS.map((chip, idx) => (
            <button
              key={idx}
              id={`prompt-chip-${idx}`}
              onClick={() => handleSend(chip.query)}
              disabled={loading}
              className={`px-3 py-1 rounded-full text-xs font-medium shrink-0 transition-all border ${
                chip.isError
                  ? "bg-rose-950/30 border-rose-500/30 text-rose-300 hover:bg-rose-900/40"
                  : "bg-[#1E293B]/60 border-[#222D3D] text-slate-300 hover:text-white hover:border-cyan-500/40 hover:bg-cyan-950/20"
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>

        {/* Input Bar */}
        <div className="p-4 bg-[#151B26] border-t border-[#222D3D]">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex items-center gap-3"
          >
            <input
              id="support-chat-input"
              type="text"
              placeholder="Ask SAGE about platform features, rules, or system errors..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              className="flex-1 bg-[#0B0F17] border border-[#222D3D] rounded-xl px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/20"
            />
            <button
              id="send-support-chat-btn"
              type="submit"
              disabled={loading || !input.trim()}
              className="px-5 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white text-sm font-semibold flex items-center gap-2 hover:opacity-90 active:scale-95 disabled:opacity-50 transition-all shadow-lg shadow-blue-500/20"
            >
              <Send className="w-4 h-4" />
              <span className="hidden sm:inline">Ask</span>
            </button>
          </form>
        </div>
      </div>

      {/* Support Ticket Modal Component */}
      <SupportTicketModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        initialData={modalData}
      />
    </>
  );
}
