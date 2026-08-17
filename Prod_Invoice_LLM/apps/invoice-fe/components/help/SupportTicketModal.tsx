"use client";

import React, { useState, useEffect } from "react";
import {
  X,
  Send,
  CheckCircle,
  AlertCircle,
  LifeBuoy,
  ChevronDown,
  Shield,
  Clock,
} from "lucide-react";

export interface EscalationData {
  category?: string;
  priority?: "LOW" | "NORMAL" | "URGENT";
  subject?: string;
  description?: string;
  transcript?: Array<{ role: string; content: string }>;
  errorCode?: string;
}

interface SupportTicketModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialData?: EscalationData | null;
}

const CATEGORIES = [
  { value: "TECHNICAL_SUPPORT", label: "Technical Support & Troubleshooting" },
  { value: "BILLING",           label: "Billing & Subscription" },
  { value: "SALES",             label: "Sales & Feature Inquiries" },
  { value: "PARTNERSHIP",       label: "Partnership & Enterprise Integrations" },
  { value: "GENERAL",           label: "General Platform Question" },
] as const;

type Priority = "LOW" | "NORMAL" | "URGENT";

const PRIORITIES: { value: Priority; label: string; sla: string; colour: string }[] = [
  { value: "LOW",    label: "Low",    sla: "< 24 hrs",  colour: "#10B981" },
  { value: "NORMAL", label: "Normal", sla: "< 12 hrs",  colour: "#3B82F6" },
  { value: "URGENT", label: "Urgent", sla: "< 2 hrs",   colour: "#EF4444" },
];

export function SupportTicketModal({
  isOpen,
  onClose,
  initialData,
}: SupportTicketModalProps) {
  const [subject, setSubject]         = useState("");
  const [category, setCategory]       = useState("TECHNICAL_SUPPORT");
  const [priority, setPriority]       = useState<Priority>("NORMAL");
  const [company, setCompany]         = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [success, setSuccess]         = useState<{ ticketNumber: string; message: string } | null>(null);

  // Sync initialData when modal opens
  useEffect(() => {
    if (isOpen) {
      setError(null);
      setSuccess(null);
      if (initialData) {
        setSubject(initialData.subject || "");
        setCategory(initialData.category || "TECHNICAL_SUPPORT");
        setPriority(initialData.priority || "NORMAL");
        setDescription(
          initialData.description ||
          (initialData.errorCode ? `Error Diagnostic: ${initialData.errorCode}\n\nPlease help resolve this issue.` : "")
        );
      } else {
        setSubject("");
        setCategory("TECHNICAL_SUPPORT");
        setPriority("NORMAL");
        setCompany("");
        setDescription("");
      }
    }
  }, [isOpen, initialData]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim()) {
      setError("Subject is required.");
      return;
    }
    if (!description.trim()) {
      setError("Description is required.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const source = initialData?.transcript && initialData.transcript.length > 0
        ? "HELP_CHATBOT"
        : "DIRECT_TICKET";

      const res = await fetch("/api/support/ticket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: subject.trim(),
          category,
          priority,
          source,
          company: company.trim() || undefined,
          description: description.trim(),
          chat_transcript: initialData?.transcript || [],
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || `Ticket submission failed (${res.status})`);
      }

      setSuccess({
        ticketNumber: data.ticket_number || "TICK-RECEIVED",
        message: data.message || "Your support ticket has been raised successfully.",
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      id="support-ticket-modal-overlay"
      className="fixed inset-0 z-50 bg-[#050816]/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-xl bg-[#151B26] border border-[#222D3D] rounded-2xl shadow-2xl overflow-hidden my-8">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#222D3D] bg-[#0F1629]/70">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
              <LifeBuoy className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white tracking-wide">
                {initialData?.transcript ? "Escalate to Support Ticket" : "Raise Support Ticket"}
              </h2>
              <p className="text-[11px] text-slate-400">
                Routed directly to <span className="text-blue-400 font-mono">Application@infinevocloud.com</span>
              </p>
            </div>
          </div>
          <button
            id="close-ticket-modal-btn"
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/5 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6">
          {success ? (
            <div id="ticket-success-card" className="text-center py-6 space-y-4">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[#10B981]/20 border border-[#10B981]/40 text-[#10B981] mb-2">
                <CheckCircle className="w-8 h-8" />
              </div>
              <h3 className="text-xl font-bold text-white">Ticket Raised Successfully!</h3>
              <p className="text-sm text-slate-300 max-w-md mx-auto">
                {success.message}
              </p>
              <div className="bg-[#0B0F17] border border-[#222D3D] rounded-xl p-4 max-w-sm mx-auto">
                <p className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold mb-1">
                  Ticket Reference Number
                </p>
                <p className="text-xl font-mono font-bold text-cyan-400">
                  {success.ticketNumber}
                </p>
              </div>
              <p className="text-xs text-slate-400 flex items-center justify-center gap-1.5 pt-2">
                <Clock className="w-3.5 h-3.5 text-blue-400" />
                Response committed within SLA to your account email.
              </p>
              <div className="pt-4">
                <button
                  id="ticket-done-btn"
                  onClick={onClose}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-semibold transition-all shadow-lg shadow-blue-600/30"
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <form id="support-ticket-form" onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="flex items-center gap-2.5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {initialData?.transcript && initialData.transcript.length > 0 && (
                <div className="p-3 bg-blue-950/40 border border-blue-500/20 rounded-xl flex items-center justify-between text-xs text-blue-300">
                  <span className="flex items-center gap-2">
                    <Shield className="w-3.5 h-3.5 text-blue-400" />
                    AI Conversation Transcript attached ({initialData.transcript.length} turns)
                  </span>
                  <span className="text-[11px] text-blue-400/80 font-mono">Auto-Attached</span>
                </div>
              )}

              {/* Subject */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="ticket-subject">
                  Subject <span className="text-rose-400">*</span>
                </label>
                <input
                  id="ticket-subject"
                  type="text"
                  placeholder="Brief summary of the issue..."
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full bg-[#0B0F17] border border-[#222D3D] rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/20"
                />
              </div>

              {/* Category & Company */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="ticket-category">
                    Category
                  </label>
                  <div className="relative">
                    <select
                      id="ticket-category"
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="w-full bg-[#0B0F17] border border-[#222D3D] rounded-xl px-4 py-2.5 text-sm text-slate-200 appearance-none pr-8 cursor-pointer focus:outline-none focus:border-blue-500/60"
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value} className="bg-[#151B26]">
                          {c.label}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="ticket-company">
                    Company / Org Name
                  </label>
                  <input
                    id="ticket-company"
                    type="text"
                    placeholder="Optional"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    className="w-full bg-[#0B0F17] border border-[#222D3D] rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/60"
                  />
                </div>
              </div>

              {/* Priority Pills */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Priority Level
                </label>
                <div className="flex gap-2">
                  {PRIORITIES.map((p) => {
                    const active = priority === p.value;
                    return (
                      <button
                        key={p.value}
                        type="button"
                        id={`ticket-priority-${p.value.toLowerCase()}`}
                        onClick={() => setPriority(p.value)}
                        style={
                          active
                            ? { borderColor: `${p.colour}80`, background: `${p.colour}20`, color: p.colour }
                            : {}
                        }
                        className={`flex-1 py-2 px-3 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-all ${
                          active
                            ? "shadow-sm"
                            : "border-[#222D3D] text-slate-400 hover:text-white bg-[#0B0F17]/50"
                        }`}
                      >
                        <span>{p.label}</span>
                        <span className="text-[10px] opacity-70 font-normal">({p.sla})</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1" htmlFor="ticket-description">
                  Description / Issue Details <span className="text-rose-400">*</span>
                </label>
                <textarea
                  id="ticket-description"
                  rows={4}
                  placeholder="Describe what happened, error codes, steps to reproduce..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full bg-[#0B0F17] border border-[#222D3D] rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500/60 resize-y min-h-[90px]"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
                >
                  Cancel
                </button>
                <button
                  id="submit-ticket-btn"
                  type="submit"
                  disabled={loading}
                  className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold text-xs flex items-center gap-2 hover:opacity-90 active:scale-[0.99] disabled:opacity-50 transition-all shadow-lg shadow-blue-500/25"
                >
                  {loading ? (
                    <>
                      <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Raising Ticket...
                    </>
                  ) : (
                    <>
                      <Send className="w-3.5 h-3.5" />
                      Submit Ticket
                    </>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
